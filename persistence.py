"""
persistence.py — Disk-backed task results + code files for crash recovery.

Supplements the in-memory BUILD_STATE (which powers SSE/UI) with:
- A JSON index per category tracking pass/fail status
- Actual .cs code files saved to results/{category}/passed/ and failed/

If the app crashes mid-batch, the next run resumes where it left off:
skips already-passed tasks AND re-commits their saved code to git.

Design decisions:
- Atomic writes (write .tmp then os.replace) to avoid corrupted JSON on crash.
- Keyed by task_id (unique database primary key from the tasks API).
- Code files named by task_id for reliable lookup on resume.
- Only used by batch/CSV mode — single-task mode does not benefit.
- Does NOT replace in-memory state — BUILD_STATE stays as-is for SSE/UI.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional


_RESULTS_DIR = "results"
_VERSION = 3


def versioned_results_dir(base_results_dir: str, nuget_version: str) -> str:
    """Return results directory nested under the NuGet/release version.

    e.g. results/26.3.0/working_with_images/passed/
    If nuget_version is empty, returns base_results_dir unchanged.
    """
    if not nuget_version:
        return base_results_dir
    return str(Path(base_results_dir) / nuget_version)


def migrate_flat_results(base_results_dir: str, nuget_version: str):
    """Move old flat-structure results into a version subfolder.

    Old: results/working_with_images.json
    New: results/26.3.0/working_with_images.json

    Safe to call multiple times — skips if already migrated or nothing to migrate.
    """
    import shutil

    if not nuget_version:
        return

    base = Path(base_results_dir)
    target = base / nuget_version

    if not base.exists():
        return

    # Check if there are flat-structure files (JSON files directly in base)
    flat_jsons = [f for f in base.iterdir() if f.is_file() and f.suffix == ".json"]
    flat_dirs = [d for d in base.iterdir() if d.is_dir() and d.name != nuget_version and not d.name.startswith(".")]

    if not flat_jsons and not flat_dirs:
        return  # Nothing to migrate

    # Don't migrate if it looks like versioned structure already (all dirs are version numbers)
    if flat_dirs and all(_looks_like_version(d.name) for d in flat_dirs):
        return

    target.mkdir(parents=True, exist_ok=True)

    migrated = 0
    for f in flat_jsons:
        dest = target / f.name
        if not dest.exists():
            shutil.move(str(f), str(dest))
            migrated += 1

    for d in flat_dirs:
        dest = target / d.name
        if not dest.exists():
            shutil.move(str(d), str(dest))
            migrated += 1

    if migrated:
        print(f"[persistence] Migrated {migrated} item(s) from {base} → {target}")


def _looks_like_version(name: str) -> bool:
    """Check if a directory name looks like a version number (e.g. 26.3.0)."""
    import re
    return bool(re.match(r"^\d+\.\d+(\.\d+)?$", name))


def _category_slug(category: str) -> str:
    """Sanitize category name for use as a directory name."""
    slug = category.lower().replace(" ", "_").replace("-", "_") if category else "uncategorized"
    return "".join(c if c.isalnum() or c == "_" else "_" for c in slug)


def _results_path(results_dir: str, category: str) -> Path:
    return Path(results_dir) / f"{_category_slug(category)}.json"


def _code_dir(results_dir: str, category: str, status: str) -> Path:
    sub = "passed" if status == "PASSED" else "failed"
    return Path(results_dir) / _category_slug(category) / sub


def _code_filename(task_id: str, task_text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task_text.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")[:80]
    return f"{task_id}_{slug}.cs"


def load_results(results_dir: str, category: str) -> dict:
    """Load previously saved results for a category.

    Returns dict of {task_id: {status, stage, task_id, task, ...}}.
    """
    path = _results_path(results_dir, category)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("_version", 0)
        if version == _VERSION:
            return data.get("tasks", {})
        # Migrate old versions: re-key by task_id
        if version in (1, 2):
            old_tasks = data.get("tasks", {})
            migrated = {}
            for _old_key, entry in old_tasks.items():
                tid = str(entry.get("task_id", _old_key))
                migrated[tid] = entry
            return migrated
        return {}
    except (json.JSONDecodeError, KeyError, OSError):
        return {}


def save_result(results_dir: str, category: str, task_id: str,
                task_text: str, status: str, stage: str = "",
                badge: str = "", code: str = "",
                metadata: dict = None):
    """Persist a single task result + code file to disk."""
    dir_path = Path(results_dir)
    dir_path.mkdir(parents=True, exist_ok=True)

    # ── Save .cs code file ──
    cs_filename = ""
    if code:
        code_path = _code_dir(results_dir, category, status)
        code_path.mkdir(parents=True, exist_ok=True)
        cs_filename = _code_filename(task_id, task_text)
        cs_file = code_path / cs_filename
        try:
            with open(cs_file, "w", encoding="utf-8") as f:
                f.write(code)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            print(f"[persistence] Warning: could not save code file {cs_filename}: {e}")
            cs_filename = ""

    # ── Clean up: remove old .cs from failed/ when task now passes ──
    if status == "PASSED":
        old_file = _code_dir(results_dir, category, "FAILED") / _code_filename(task_id, task_text)
        if old_file.exists():
            try:
                old_file.unlink()
            except OSError:
                pass

    # ── Update JSON index ──
    path = _results_path(results_dir, category)
    existing = load_results(results_dir, category) if path.exists() else {}

    existing[str(task_id)] = {
        "task_id": task_id,
        "task": task_text[:200],
        "status": status,
        "stage": stage,
        "badge": badge,
        "cs_file": cs_filename,
        "metadata": metadata or {},
    }

    payload = {
        "_version": _VERSION,
        "category": category,
        "tasks": existing,
    }
    tmp_path = path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    except OSError as e:
        print(f"[persistence] Warning: could not save results for {category}: {e}")


def is_task_passed(results_dir: str, category: str,
                   task_id: str, task_text: str) -> bool:
    """Check if a task already passed in a previous run."""
    results = load_results(results_dir, category)
    entry = results.get(str(task_id))
    return bool(entry and entry.get("status") == "PASSED")


def load_cached_task(results_dir: str, category: str,
                     task_id: str, task_text: str) -> Optional[dict]:
    """Load a previously passed task's code and metadata from disk."""
    results = load_results(results_dir, category)
    entry = results.get(str(task_id))
    if not entry or entry.get("status") != "PASSED":
        return None

    cs_filename = entry.get("cs_file", "")
    code = ""
    if cs_filename:
        cs_path = _code_dir(results_dir, category, "PASSED") / cs_filename
        if cs_path.exists():
            try:
                code = cs_path.read_text(encoding="utf-8")
            except OSError:
                pass

    if not code:
        return None

    return {
        "code": code,
        "stage": entry.get("stage", ""),
        "badge": entry.get("badge", "CACHED"),
        "metadata": entry.get("metadata", {}),
    }


def clear_results(results_dir: str, category: str = ""):
    """Clear saved results + code files for a category (or all if empty)."""
    import shutil
    dir_path = Path(results_dir)
    if not dir_path.exists():
        return
    if category:
        path = _results_path(results_dir, category)
        if path.exists():
            path.unlink(missing_ok=True)
        code_root = dir_path / _category_slug(category)
        if code_root.exists():
            shutil.rmtree(code_root, ignore_errors=True)
    else:
        for item in dir_path.iterdir():
            if item.is_file():
                item.unlink(missing_ok=True)
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)


def get_resume_stats(results_dir: str, category: str) -> dict:
    """Get stats for display: how many passed/failed tasks are cached."""
    results = load_results(results_dir, category)
    passed = sum(1 for v in results.values() if v.get("status") == "PASSED")
    failed = sum(1 for v in results.values() if v.get("status") == "FAILED")
    return {"passed": passed, "failed": failed, "total": len(results)}


# ── Disk scan for PR creation ──

def list_result_versions(base_results_dir: str) -> list:
    """List all version directories under results/."""
    base = Path(base_results_dir)
    if not base.exists():
        return []
    versions = []
    for d in sorted(base.iterdir()):
        if d.is_dir() and _looks_like_version(d.name):
            versions.append(d.name)
    return versions


def scan_disk_results(results_dir: str) -> dict:
    """Scan persisted results directory and return per-category summary.

    Returns:
        {
            "category_name": {
                "passed": int,
                "failed": int,
                "total": int,
                "examples": [
                    {
                        "task_id": str,
                        "task": str,
                        "status": str,
                        "stage": str,
                        "badge": str,
                        "cs_file": str,
                        "has_code": bool,
                        "metadata": {title, filename, description, tags, apis_used, difficulty},
                    },
                    ...
                ],
            },
            ...
        }
    """
    rdir = Path(results_dir)
    if not rdir.exists():
        return {}

    # Find all category JSON files
    categories = {}
    for json_file in sorted(rdir.glob("*.json")):
        cat_slug = json_file.stem
        results = load_results(results_dir, cat_slug)
        if not results:
            continue

        examples = []
        passed = 0
        failed = 0

        for task_id, entry in results.items():
            status = entry.get("status", "UNKNOWN")
            if status == "PASSED":
                passed += 1
            elif status == "FAILED":
                failed += 1

            # Check if code file exists on disk
            cs_file = entry.get("cs_file", "")
            has_code = False
            if cs_file and status == "PASSED":
                code_path = _code_dir(results_dir, cat_slug, "PASSED") / cs_file
                has_code = code_path.exists()

            metadata = entry.get("metadata", {})
            examples.append({
                "task_id": task_id,
                "task": entry.get("task", ""),
                "status": status,
                "stage": entry.get("stage", ""),
                "badge": entry.get("badge", ""),
                "cs_file": cs_file,
                "has_code": has_code,
                "metadata": {
                    "title": metadata.get("title", ""),
                    "filename": metadata.get("filename", ""),
                    "description": metadata.get("description", ""),
                    "tags": metadata.get("tags", []),
                    "apis_used": metadata.get("apis_used", []),
                    "difficulty": metadata.get("difficulty", ""),
                },
            })

        # Try to recover original category name from first entry or slug
        original_name = cat_slug.replace("_", " ").title()
        for ex in examples:
            # The task text might hint at the category but we don't have it stored
            # The category slug is reliable enough
            break

        categories[cat_slug] = {
            "passed": passed,
            "failed": failed,
            "total": len(examples),
            "examples": examples,
        }

    return categories


def load_passed_examples(results_dir: str, category_slug: str) -> list:
    """Load all passed examples for a category with their code from disk.

    Returns list of dicts:
        [{task_id, task, code, stage, badge, metadata}, ...]
    """
    results = load_results(results_dir, category_slug)
    examples = []

    for task_id, entry in results.items():
        if entry.get("status") != "PASSED":
            continue

        cs_file = entry.get("cs_file", "")
        code = ""
        if cs_file:
            code_path = _code_dir(results_dir, category_slug, "PASSED") / cs_file
            if code_path.exists():
                try:
                    code = code_path.read_text(encoding="utf-8")
                except OSError:
                    continue  # skip if code can't be read

        if not code:
            continue  # no code = can't create PR for this one

        examples.append({
            "task_id": task_id,
            "task": entry.get("task", ""),
            "code": code,
            "stage": entry.get("stage", ""),
            "badge": entry.get("badge", ""),
            "metadata": entry.get("metadata", {}),
        })

    return examples
