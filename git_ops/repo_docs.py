"""
git_ops/repo_docs.py — Scan repo and generate cumulative agents.md / README.md.

Used by the manual 'Update Repo Docs' action to build accurate,
cumulative documentation that reflects all files on the main branch.
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from git_ops.agents_md import _generate_run_id
from git_ops.agents_content import (
    build_boundaries,
    build_code_intelligence_sections,
    build_command_reference,
    build_frontmatter,
    build_persona,
    build_testing_guide,
    extract_category_metadata,
    load_anti_patterns,
    load_category_tips,
    load_domain_knowledge,
)


# Directories to skip when scanning for categories.
_SKIP_DIRS = {".git", ".github", ".vscode", "node_modules", "__pycache__", "bin", "obj"}


def _normalize_name(name: str) -> str:
    """Lowercase, replace spaces with hyphens, collapse duplicates."""
    n = name.lower().replace(" ", "-")
    return re.sub(r"-+", "-", n).strip("-")


def normalize_repo_folders(repo_path: str) -> Dict[str, str]:
    """Rename category folders and their .cs files to lowercase-hyphenated form.

    Uses ``git mv`` so that git tracks renames properly.
    Returns ``{old_path: new_path}`` for every item that was renamed.
    """
    root = Path(repo_path)
    renamed: Dict[str, str] = {}

    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in _SKIP_DIRS:
            continue

        # --- Rename folder ---
        norm_dir = _normalize_name(child.name)
        folder = child
        if norm_dir != child.name:
            target = root / norm_dir
            if target.exists():
                continue
            subprocess.run(
                ["git", "mv", str(child), str(target)],
                cwd=repo_path, check=True, capture_output=True, text=True,
            )
            renamed[child.name] = norm_dir
            folder = target

        # --- Rename .cs files inside the folder ---
        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.suffix != ".cs":
                continue
            stem_norm = _normalize_name(f.stem)
            new_name = f"{stem_norm}.cs"
            if new_name != f.name:
                target_file = folder / new_name
                if target_file.exists():
                    continue
                subprocess.run(
                    ["git", "mv", str(f), str(target_file)],
                    cwd=repo_path, check=True, capture_output=True, text=True,
                )
                renamed[f"{folder.name}/{f.name}"] = f"{folder.name}/{new_name}"

    return renamed


def scan_repo(repo_path: str) -> Dict[str, List[str]]:
    """Walk the repo and return ``{category_name: [filename.cs, ...]}``."""
    root = Path(repo_path)
    categories: Dict[str, List[str]] = {}

    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in _SKIP_DIRS:
            continue

        cs_files = sorted(f.name for f in child.iterdir() if f.is_file() and f.suffix == ".cs")
        if cs_files:
            categories[child.name] = cs_files

    return categories


def generate_cumulative_agents_md(
    scan: Dict[str, List[str]],
    tfm: str = "net10.0",
    nuget_version: str = "26.2.0",
    run_id: str = None,
    error_catalog_path: str = "",
    error_fixes_path: str = "",
    kb_path: str = "",
) -> str:
    """Generate root agents.md from a real repo scan (cumulative).

    When resource paths are provided, injects prescriptive sections:
    - Enhanced code conventions with examples
    - Common mistakes (anti-patterns) from error_catalog + error_fixes
    - Domain knowledge from kb.json
    - Command reference for dotnet build/run
    """
    if not run_id:
        run_id = _generate_run_id()

    total = sum(len(files) for files in scan.values())
    current_date = datetime.now().strftime("%Y-%m-%d")

    category_details = ""
    for cat, files in sorted(scan.items()):
        cat_slug = _normalize_name(cat)
        category_details += f"### {cat}\n"
        category_details += f"- Examples: {len(files)}\n"
        category_details += f"- Guide: [agents.md](./{cat_slug}/agents.md)\n\n"

    # Build sections from resource files
    frontmatter = build_frontmatter(tfm, nuget_version)
    persona_section = build_persona()
    boundaries_section = build_boundaries()
    anti_patterns_section = load_anti_patterns(error_catalog_path, error_fixes_path) if error_catalog_path else ""
    domain_section = load_domain_knowledge(kb_path) if kb_path else ""
    command_section = build_command_reference(tfm, nuget_version)
    testing_section = build_testing_guide(tfm)

    return f"""{frontmatter}# Aspose.PDF for .NET Examples

AI-friendly repository containing validated C# examples for Aspose.PDF for .NET API.

{persona_section}## Repository Overview

This repository contains **{total}** working code examples demonstrating Aspose.PDF for .NET capabilities.

**Statistics** (as of {current_date}):
- Total Examples: {total}
- Categories: {len(scan)}

## Category Details

{category_details}{boundaries_section}{anti_patterns_section}{domain_section}{command_section}{testing_section}## How to Use These Examples

### Prerequisites
- .NET SDK ({tfm.replace('net', '').replace('.0', '.0')} or higher)
- Aspose.PDF for .NET ({nuget_version} or higher)
- NuGet package restore enabled

### Running an Example
1. Navigate to any category folder
2. Each .cs file is a standalone Console Application
3. Ensure `input.pdf` exists in the same directory (where required)
4. Compile and run:
   ```bash
   dotnet run <example-file.cs>
   ```

<!-- AUTOGENERATED:START -->
Updated: {current_date} | Run: `{run_id}` | Examples: {total} | Categories: {len(scan)}
<!-- AUTOGENERATED:END -->

---

*This repository is maintained by automated code generation. Last updated: {current_date} | Total examples: {total}*
"""


def generate_cumulative_category_agents_md(
    category: str,
    files: List[str],
    run_id: str = None,
    kb_path: str = "",
    repo_path: str = "",
    tfm: str = "net10.0",
    nuget_version: str = "26.2.0",
) -> str:
    """Generate per-category agents.md from actual file list.

    When *repo_path* is provided, enriches output with code intelligence
    (required namespaces, common code pattern, file summary table).
    When *kb_path* is provided, injects category-specific tips.
    """
    if not run_id:
        run_id = _generate_run_id()

    current_date = datetime.now().strftime("%Y-%m-%d")

    # Frontmatter + persona
    frontmatter = build_frontmatter(tfm, nuget_version, is_category=True, category_name=category)
    persona_section = build_persona(is_category=True, category_name=category)

    # Code intelligence from actual .cs files (namespaces + pattern + table)
    code_intel = build_code_intelligence_sections(repo_path, category, files) if repo_path else ""

    if code_intel:
        file_section = code_intel
    else:
        # Fallback: simple file list
        file_list = ""
        for filename in sorted(files):
            display = filename.replace(".cs", "")
            file_list += f"- [{display}](./{filename})\n"
        file_section = f"## Files in this folder\n{file_list}\n"

    # Category-specific tips from kb.json
    category_tips = load_category_tips(kb_path, category) if kb_path else ""

    return f"""{frontmatter}# AGENTS - {category}

{persona_section}## Scope
- This folder contains examples for **{category}**.
- Files are standalone `.cs` examples stored directly in this folder.

{file_section}## Category Statistics
- Total examples: {len(files)}

{category_tips}## General Tips
- See parent [agents.md](../agents.md) for:
  - **Boundaries** — Always / Ask First / Never rules for all examples
  - **Common Mistakes** — verified anti-patterns that cause build failures
  - **Domain Knowledge** — cross-cutting API-specific gotchas
  - **Testing Guide** — build and run verification steps
- Review code examples in this folder for {category} patterns

<!-- AUTOGENERATED:START -->
Updated: {current_date} | Run: `{run_id}`
<!-- AUTOGENERATED:END -->
"""


def generate_index_json(
    scan: Dict[str, List[str]],
    tfm: str = "net10.0",
    nuget_version: str = "26.2.0",
    repo_path: str = "",
) -> str:
    """Generate index.json — a machine-readable manifest of the repository.

    Returns a JSON string with product metadata, total stats, and
    per-category data including files, required namespaces, and key APIs.
    """
    total = sum(len(files) for files in scan.values())
    current_date = datetime.now().strftime("%Y-%m-%d")

    categories = []
    for cat_name, files in sorted(scan.items()):
        cat_entry = {
            "name": cat_name,
            "file_count": len(files),
            "files": sorted(files),
        }

        # Enrich with code intelligence if repo is available
        if repo_path:
            meta = extract_category_metadata(repo_path, cat_name, files)
            cat_entry["required_namespaces"] = meta["required_namespaces"]
            cat_entry["key_apis"] = meta["key_apis"]

        categories.append(cat_entry)

    index = {
        "product": "Aspose.PDF",
        "platform": "net",
        "framework": tfm,
        "package_version": nuget_version,
        "total_examples": total,
        "total_categories": len(scan),
        "last_updated": current_date,
        "categories": categories,
    }

    return json.dumps(index, indent=2, ensure_ascii=False) + "\n"


def update_readme_categories(readme_content: str, scan: Dict[str, List[str]]) -> str:
    """Update the category listing section in README.md.

    Looks for a markdown list under a heading containing 'Structure'
    and replaces it with the current scan results.
    """
    if not readme_content or not scan:
        return readme_content

    # Build new category listing
    lines = []
    for cat, files in sorted(scan.items()):
        lines.append(f"- `{cat}/` - {len(files)} example(s)")
    new_listing = "\n".join(lines)

    # Try to find and replace existing listing under "Repository Structure" heading
    pattern = r"(## Repository Structure\s*\n\s*Examples are organized by feature category:\s*\n)((?:- `[^`]+/`[^\n]*\n?)+)"
    match = re.search(pattern, readme_content)
    if match:
        return readme_content[:match.start(2)] + new_listing + "\n" + readme_content[match.end(2):]

    # Fallback: try simpler pattern
    pattern2 = r"(## Repository Structure\s*\n[^\n]*\n)((?:- `[^`]+`[^\n]*\n?)+)"
    match2 = re.search(pattern2, readme_content)
    if match2:
        return readme_content[:match2.start(2)] + new_listing + "\n" + readme_content[match2.end(2):]

    return readme_content
