"""
git_ops/release_notes.py -- Auto-generate GitHub Release notes by diffing
index.json on the release branch vs the previous version on main/base branch.
"""

import base64
import json
from datetime import date
from typing import Optional


def _fetch_index(gh, owner: str, repo: str, branch: str) -> Optional[dict]:
    """Fetch and parse index.json from a branch.

    index.json is typically >1MB so the GitHub Contents API refuses it.
    Falls back to the git tree + blob API which has no size limit.
    """
    # Try Contents API first (works for small files / cache hits)
    file_data = gh.get_file(owner, repo, "index.json", branch)
    if file_data and file_data.get("content"):
        try:
            raw = base64.b64decode(file_data["content"]).decode("utf-8")
            return json.loads(raw)
        except Exception:
            pass

    # Fallback: resolve blob SHA via tree API, then fetch raw blob
    try:
        tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}"
        r = gh._session.get(tree_url, headers=gh._headers, timeout=15)
        if r.status_code != 200:
            return None
        blob_sha = next(
            (item["sha"] for item in r.json().get("tree", []) if item["path"] == "index.json"),
            None,
        )
        if not blob_sha:
            return None

        blob_url = f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{blob_sha}"
        rb = gh._session.get(blob_url, headers=gh._headers, timeout=30)
        if rb.status_code != 200:
            return None
        raw = base64.b64decode(rb.json()["content"]).decode("utf-8")
        return json.loads(raw)
    except Exception as e:
        print(f"[ReleaseNotes] Could not fetch index.json from {branch} via blob API: {e}")
        return None


def _category_map(index: dict) -> dict:
    """Return {category_name: file_set} from an index.json dict."""
    result = {}
    for cat in index.get("categories", []):
        name = cat.get("name", "")
        files = set(cat.get("files", []))
        if name:
            result[name] = files
    return result


def generate_release_notes(
    gh,
    owner: str,
    repo: str,
    release_branch: str,
    base_branch: str,
    new_version: str,
    framework: str = "net10.0",
) -> str:
    """
    Build rich GitHub Release notes by comparing index.json on release_branch
    vs base_branch (main / previous release).

    Falls back to a minimal stub if index.json is unavailable on either branch.
    """
    new_index = _fetch_index(gh, owner, repo, release_branch)
    old_index = _fetch_index(gh, owner, repo, base_branch)

    # ── Fallback: no index available ──
    if not new_index:
        return (
            f"Examples generated for **Aspose.PDF for .NET {new_version}**.\n\n"
            f"- Target framework: `{framework}`\n"
            f"- NuGet package: `Aspose.PDF {new_version}`\n"
        )

    total_new = new_index.get("total_examples", 0)
    total_cats = new_index.get("total_categories", 0)
    fw = new_index.get("framework", framework)
    updated = new_index.get("last_updated", str(date.today()))

    new_cats = _category_map(new_index)
    old_cats = _category_map(old_index) if old_index else {}

    added_categories = sorted(k for k in new_cats if k not in old_cats)
    updated_categories = []
    for name, files in sorted(new_cats.items()):
        if name in old_cats:
            added_files = files - old_cats[name]
            removed_files = old_cats[name] - files
            if added_files or removed_files:
                updated_categories.append((name, len(files), len(added_files), len(removed_files)))

    total_old = old_index.get("total_examples", 0) if old_index else 0
    net_change = total_new - total_old

    lines = []

    # ── Header ──
    lines.append(f"## Aspose.PDF for .NET {new_version} — Examples Release")
    lines.append("")
    lines.append(
        f"Agentic, build-validated C# code examples for **Aspose.PDF for .NET {new_version}**. "
        "Every example compiles and runs successfully against the target framework."
    )
    lines.append("")

    # ── Summary table ──
    lines.append("### Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total examples | **{total_new:,}** |")
    if net_change != 0:
        sign = "+" if net_change > 0 else ""
        lines.append(f"| Change from previous | `{sign}{net_change}` |")
    lines.append(f"| Categories | {total_cats} |")
    if added_categories:
        lines.append(f"| New categories | {len(added_categories)} |")
    lines.append(f"| Target framework | `{fw}` |")
    lines.append(f"| NuGet package | `Aspose.PDF {new_version}` |")
    lines.append(f"| Last updated | {updated} |")
    lines.append("")

    # ── New categories ──
    if added_categories:
        lines.append("### New Categories")
        lines.append("")
        for name in added_categories:
            count = len(new_cats[name])
            lines.append(f"- `{name}` — {count} example{'s' if count != 1 else ''}")
        lines.append("")

    # ── Updated categories ──
    if updated_categories:
        lines.append("### Updated Categories")
        lines.append("")
        lines.append("| Category | Total | Added | Removed |")
        lines.append("|----------|-------|-------|---------|")
        for name, total, added, removed in updated_categories:
            lines.append(f"| `{name}` | {total} | +{added} | -{removed} |")
        lines.append("")

    # ── Full category breakdown ──
    lines.append("### All Categories")
    lines.append("")
    lines.append("| Category | Examples |")
    lines.append("|----------|----------|")
    for name, files in sorted(new_cats.items()):
        marker = " ✨" if name in added_categories else ""
        lines.append(f"| `{name}`{marker} | {len(files)} |")
    lines.append("")

    # ── Footer ──
    lines.append("---")
    lines.append("")
    lines.append(
        "*Examples are automatically generated, compiled, and validated by the "
        "[Aspose PDF Examples Generator](https://github.com/aspose-pdf/agentic-net-examples). "
        "Each `.cs` file is a standalone, runnable console application.*"
    )

    return "\n".join(lines)
