#!/usr/bin/env python3
"""Verify all PASSED .cs files actually compile.

Moves broken files from passed/ → failed/ and updates the JSON.
Uses a single persistent build workspace with pre-restored NuGet to
avoid repeated restore overhead (~1s per file instead of ~5s).

Usage:
    python scripts/verify_passed.py [--dry-run] [--version 26.3.0]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

CSPROJ_TEMPLATE = """\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>{tfm}</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Aspose.PDF" Version="{nuget}" />
  </ItemGroup>
</Project>"""

BUILD_DIR = Path("/tmp/verify_passed_build")


def setup_workspace(tfm: str, nuget: str):
    """Create build workspace and restore NuGet once."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    csproj = BUILD_DIR / "test.csproj"
    csproj.write_text(CSPROJ_TEMPLATE.format(tfm=tfm, nuget=nuget))
    # Write dummy Program.cs for initial restore
    (BUILD_DIR / "Program.cs").write_text("class P { static void Main() {} }\n")
    result = subprocess.run(
        ["dotnet", "restore", "--nologo"],
        cwd=BUILD_DIR, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"FATAL: dotnet restore failed:\n{result.stdout}\n{result.stderr}")
        sys.exit(1)
    print("NuGet restored successfully.")


def try_build(cs_path: Path) -> tuple[bool, str]:
    """Copy .cs into workspace and try to compile. Returns (ok, errors)."""
    shutil.copy2(cs_path, BUILD_DIR / "Program.cs")
    result = subprocess.run(
        ["dotnet", "build", "--no-restore", "--no-incremental", "--nologo", "-v", "q"],
        cwd=BUILD_DIR, capture_output=True, text=True, timeout=60,
    )
    if result.returncode == 0:
        return True, ""
    errors = [l.strip() for l in result.stdout.split("\n") if "error CS" in l]
    return False, "; ".join(errors[:3])


def demote_to_failed(results_dir: str, cat_slug: str, task_id: str,
                     cs_filename: str, error_msg: str, dry_run: bool):
    """Move .cs from passed/ → failed/ and update JSON status."""
    passed_dir = Path(results_dir) / cat_slug / "passed"
    failed_dir = Path(results_dir) / cat_slug / "failed"
    cs_src = passed_dir / cs_filename
    cs_dst = failed_dir / cs_filename

    if dry_run:
        print(f"    [DRY RUN] Would move {cs_filename} to failed/ and update JSON")
        return

    # Move file
    failed_dir.mkdir(parents=True, exist_ok=True)
    if cs_src.exists():
        shutil.move(str(cs_src), str(cs_dst))

    # Update JSON
    json_path = Path(results_dir) / f"{cat_slug}.json"
    if not json_path.exists():
        return
    data = json.loads(json_path.read_text(encoding="utf-8"))
    tasks = data.get("tasks", {})
    if task_id in tasks:
        tasks[task_id]["status"] = "FAILED"
        tasks[task_id]["stage"] = "exhausted"
        tasks[task_id]["build_output"] = f"[POST-VERIFY] {error_msg}"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Verify PASSED .cs files compile")
    parser.add_argument("--dry-run", action="store_true", help="Don't move files, just report")
    parser.add_argument("--version", default="26.3.0", help="Results version (default: 26.3.0)")
    parser.add_argument("--tfm", default="net10.0", help="Target framework (default: net10.0)")
    parser.add_argument("--nuget", default="26.3.0", help="Aspose.PDF NuGet version (default: 26.3.0)")
    parser.add_argument("--category", default="", help="Only check this category slug")
    args = parser.parse_args()

    results_dir = str(Path(__file__).resolve().parent.parent / "results" / args.version)
    if not Path(results_dir).exists():
        print(f"Results dir not found: {results_dir}")
        sys.exit(1)

    setup_workspace(args.tfm, args.nuget)

    total_tested = 0
    total_failed = 0
    failures = []

    # Scan categories
    for item in sorted(os.listdir(results_dir)):
        if args.category and item != args.category:
            continue
        passed_dir = Path(results_dir) / item / "passed"
        if not passed_dir.is_dir():
            continue
        cs_files = sorted([f for f in os.listdir(passed_dir) if f.endswith(".cs")])
        if not cs_files:
            continue

        # Load JSON to map cs_file → task_id
        json_path = Path(results_dir) / f"{item}.json"
        task_map = {}  # cs_filename → task_id
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            for tid, entry in data.get("tasks", {}).items():
                cs = entry.get("cs_file", "")
                if cs:
                    task_map[cs] = tid

        cat_fails = 0
        for cs in cs_files:
            total_tested += 1
            ok, errs = try_build(passed_dir / cs)
            if not ok:
                total_failed += 1
                cat_fails += 1
                task_id = task_map.get(cs, "?")
                short_err = errs[:150] if errs else "compile error"
                print(f"  ❌ {item}/{cs[:70]}  (task {task_id})")
                print(f"     {short_err}")
                failures.append((item, cs, task_id, errs))
                demote_to_failed(results_dir, item, task_id, cs, errs, args.dry_run)

        if cat_fails:
            print(f"  → {item}: {cat_fails}/{len(cs_files)} failed\n")

        # Progress indicator
        if total_tested % 100 == 0:
            print(f"  ... {total_tested} files checked, {total_failed} failures so far")

    print(f"\n{'='*70}")
    print(f"TOTAL: {total_failed} failures out of {total_tested} PASSED files")
    if args.dry_run and total_failed > 0:
        print(f"\nRun without --dry-run to move failures and update JSONs")


if __name__ == "__main__":
    main()
