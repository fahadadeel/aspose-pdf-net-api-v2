"""
scripts/rollback_snapshot.py — Pre-flight snapshot helper for Flow A / Flow B.

A snapshot is a JSON file that captures the exact state of the GitHub
repo (branch tips, tags, .env version) BEFORE a merge orchestrator or
promotion runs. After the flow finishes, the file is updated with the
"after" state (merged PR numbers, new squash SHA, new tag) so that the
rollback CLI knows exactly what to undo.

All snapshots live in ``{project_root}/rollback_snapshots/`` which is
gitignored. Files are atomically written via a tempfile + rename so
they are never left in a half-written state.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from git_ops.github_api import GitHubAPI


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = _PROJECT_ROOT / "rollback_snapshots"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gen_id(flow: str) -> str:
    """Generate a short, sortable, unique snapshot id."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(3)
    return f"{ts}-{flow}-{suffix}"


def _ensure_dir() -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically: tempfile + rename."""
    _ensure_dir()
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_env_keys(env_path: Path, keys: list[str]) -> dict:
    """Read selected keys from a .env-style file. Missing keys → empty string."""
    out = {k: "" for k in keys}
    if not env_path.exists():
        return out
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k in out:
                out[k] = v.strip()
    except Exception:
        pass
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Flow A snapshots (per-category PR merges → release branch)
# ─────────────────────────────────────────────────────────────────────────────

def create_flow_a_snapshot(
    gh: GitHubAPI,
    owner: str,
    repo: str,
    base_branch: str,
    planned_prs: list[dict],
) -> Path:
    """Capture release-branch tip + the list of PRs we plan to merge.

    Call this AFTER the plan is confirmed but BEFORE the first merge.
    Returns the snapshot file path.
    """
    snap_id = _gen_id("A")
    base_sha = gh.get_branch_sha(owner, repo, base_branch) or ""
    data = {
        "id": snap_id,
        "timestamp": _now_iso(),
        "flow": "A",
        "owner": owner,
        "repo": repo,
        "base_branch": base_branch,
        "base_sha_before": base_sha,
        "base_sha_after": None,
        "planned_prs": [
            {
                "number": p["number"],
                "title": p.get("title", ""),
                "head_ref": p.get("head_ref", ""),
                "head_sha": p.get("head_sha", ""),
            }
            for p in planned_prs
        ],
        "merged_prs": [],
        "skipped_prs": [],
        "failed_prs": [],
        "completed": False,
    }
    path = SNAPSHOT_DIR / f"{snap_id}.json"
    _atomic_write(path, data)
    return path


def finalize_flow_a_snapshot(
    path: Path,
    gh: GitHubAPI,
    batch_summary: dict,
) -> None:
    """Update a Flow A snapshot with the post-merge state.

    Records base_sha_after and the merged/skipped/failed PR lists from
    the batch summary returned by ``run_merge_batch``.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    owner = data["owner"]
    repo = data["repo"]
    base_branch = data["base_branch"]
    data["base_sha_after"] = gh.get_branch_sha(owner, repo, base_branch) or ""
    merged, skipped, failed = [], [], []
    for detail in batch_summary.get("details", []):
        entry = {
            "pr_number": detail.get("pr_number"),
            "reason": detail.get("reason", ""),
            "elapsed": detail.get("elapsed", 0),
        }
        status = detail.get("status")
        if status == "merged":
            merged.append(entry)
        elif status == "skipped":
            skipped.append(entry)
        else:
            failed.append(entry)
    data["merged_prs"] = merged
    data["skipped_prs"] = skipped
    data["failed_prs"] = failed
    data["completed"] = True
    data["finalized_at"] = _now_iso()
    _atomic_write(path, data)


# ─────────────────────────────────────────────────────────────────────────────
# Flow B snapshots (release → main promotion)
# ─────────────────────────────────────────────────────────────────────────────

def create_flow_b_snapshot(
    gh: GitHubAPI,
    owner: str,
    repo: str,
    release_branch: str,
    new_version: str,
    env_path: Optional[Path] = None,
) -> Path:
    """Capture main tip + release tip + .env version before promotion."""
    snap_id = _gen_id("B")
    main_sha = gh.get_branch_sha(owner, repo, "main") or ""
    release_sha = gh.get_branch_sha(owner, repo, release_branch) or ""
    env_before = {}
    if env_path is None:
        env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        env_before = _read_env_keys(env_path, [
            "NUGET_VERSION", "REPO_BRANCH", "PR_TARGET_BRANCH",
        ])
    data = {
        "id": snap_id,
        "timestamp": _now_iso(),
        "flow": "B",
        "owner": owner,
        "repo": repo,
        "release_branch": release_branch,
        "main_sha_before": main_sha,
        "release_sha_before": release_sha,
        "new_version": new_version,
        "new_tag": f"v{new_version}",
        "env_before": env_before,
        "main_sha_after": None,
        "pr_number": None,
        "pr_url": None,
        "release_url": None,
        "completed": False,
    }
    path = SNAPSHOT_DIR / f"{snap_id}.json"
    _atomic_write(path, data)
    return path


def finalize_flow_b_snapshot(
    path: Path,
    gh: GitHubAPI,
    pr_number: Optional[int] = None,
    pr_url: str = "",
    release_url: str = "",
) -> None:
    """Update a Flow B snapshot with post-promotion state."""
    data = json.loads(path.read_text(encoding="utf-8"))
    owner = data["owner"]
    repo = data["repo"]
    data["main_sha_after"] = gh.get_branch_sha(owner, repo, "main") or ""
    data["pr_number"] = pr_number
    data["pr_url"] = pr_url
    data["release_url"] = release_url
    data["completed"] = True
    data["finalized_at"] = _now_iso()
    _atomic_write(path, data)


# ─────────────────────────────────────────────────────────────────────────────
# Load / list helpers (used by scripts/rollback.py)
# ─────────────────────────────────────────────────────────────────────────────

def load_snapshot(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def list_snapshots(flow: Optional[str] = None) -> list[Path]:
    """Return snapshot file paths newest-first. Filter by flow ('A'/'B') if given."""
    if not SNAPSHOT_DIR.exists():
        return []
    paths = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
    if not flow:
        return paths
    out: list[Path] = []
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("flow") == flow:
                out.append(p)
        except Exception:
            continue
    return out


def resolve_snapshot(ref: str) -> Optional[Path]:
    """Accept a snapshot id, filename, 'latest', 'latest-a', 'latest-b', or path."""
    if not ref:
        return None
    # Exact path
    p = Path(ref)
    if p.exists() and p.is_file():
        return p
    # latest / latest-a / latest-b
    low = ref.lower()
    if low in ("latest", "latest-a", "latest-b"):
        flow = None if low == "latest" else low.split("-")[1].upper()
        items = list_snapshots(flow=flow)
        return items[0] if items else None
    # id (with or without .json)
    if not ref.endswith(".json"):
        ref = ref + ".json"
    candidate = SNAPSHOT_DIR / ref
    return candidate if candidate.exists() else None
