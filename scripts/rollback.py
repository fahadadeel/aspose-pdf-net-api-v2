#!/usr/bin/env python3
"""
scripts/rollback.py — Rollback CLI for Flow A / Flow B.

Subcommands:
  list                         List saved snapshots (newest first)
  show <ref>                   Print a snapshot's contents
  snapshot --flow A|B          Capture a manual pre-flight snapshot
  revert-flow-a <ref>          Create a revert PR for every merge made on the
                               release branch since a Flow A snapshot was taken
  revert-flow-b <ref>          Create a revert PR for the promotion squash commit,
                               delete the new tag/release, and print .env restore
                               instructions

<ref> may be:
  - a snapshot id       e.g. 20260410-143022-A-a1b2c3
  - a snapshot filename e.g. 20260410-143022-A-a1b2c3.json
  - an absolute path    e.g. /path/to/snapshot.json
  - 'latest'            most-recent snapshot regardless of flow
  - 'latest-a'          most-recent Flow A snapshot
  - 'latest-b'          most-recent Flow B snapshot

All revert actions print a plan and require explicit confirmation unless
--yes is passed. Revert PRs are always created through normal merge flow
(no force-push, no history rewrite) so they respect repo rulesets.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Make project root importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from config import load_config  # noqa: E402
from git_ops.github_api import GitHubAPI  # noqa: E402
from scripts.rollback_snapshot import (  # noqa: E402
    SNAPSHOT_DIR,
    create_flow_a_snapshot,
    create_flow_b_snapshot,
    list_snapshots,
    load_snapshot,
    resolve_snapshot,
)


# ─────────────────────────────────────────────────────────────────────────────
# Generic helpers
# ─────────────────────────────────────────────────────────────────────────────

def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        answer = input(f"\n  {prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return False
    return answer == "y"


def _run_git(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git subcommand, streaming output on failure."""
    result = subprocess.run(
        ["git", *cmd],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        print(f"  ✗ git {' '.join(cmd)} failed")
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip())
        raise SystemExit(1)
    return result


def _require_clean_worktree(repo_path: Path) -> None:
    r = _run_git(["status", "--porcelain"], repo_path, check=True)
    if r.stdout.strip():
        print(f"  ✗ Working tree {repo_path} is not clean. Commit/stash first.")
        print(r.stdout)
        raise SystemExit(1)


def _get_github_client() -> tuple[GitHubAPI, GitHubAPI, str, str, Path]:
    """Return (gh_bot, gh_merge, owner, repo, local_repo_path)."""
    cfg = load_config()
    if not cfg.git.repo_token:
        print("✗ REPO_TOKEN not set in .env — cannot call GitHub API.")
        raise SystemExit(1)
    gh_bot = GitHubAPI(cfg.git.repo_token)
    gh_merge = GitHubAPI(cfg.git.personal_token or cfg.git.repo_token)
    owner, repo = GitHubAPI.extract_repo_info(cfg.git.repo_url)
    if not owner or not repo:
        print(f"✗ Could not parse repo URL: {cfg.git.repo_url}")
        raise SystemExit(1)
    local = Path(cfg.git.repo_path)
    if not (local / ".git").exists():
        print(f"✗ Local repo not found at {local}")
        raise SystemExit(1)
    return gh_bot, gh_merge, owner, repo, local


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand: list
# ─────────────────────────────────────────────────────────────────────────────

def cmd_list(args: argparse.Namespace) -> None:
    snaps = list_snapshots(flow=args.flow)
    if not snaps:
        print("  No snapshots found.")
        return
    print(f"\n  {'ID':<32}  {'Flow':<4}  {'When':<20}  Summary")
    print(f"  {'-' * 32}  {'-' * 4}  {'-' * 20}  {'-' * 40}")
    for p in snaps:
        try:
            data = load_snapshot(p)
        except Exception as e:
            print(f"  {p.stem:<32}  ?     ?                     <unreadable: {e}>")
            continue
        flow = data.get("flow", "?")
        ts = data.get("timestamp", "")[:19].replace("T", " ")
        done = "✓" if data.get("completed") else "…"
        if flow == "A":
            n_merged = len(data.get("merged_prs", []))
            n_planned = len(data.get("planned_prs", []))
            summary = f"{done} {n_merged}/{n_planned} PRs merged → {data.get('base_branch', '')}"
        elif flow == "B":
            ver = data.get("new_version", "?")
            pr = data.get("pr_number") or "?"
            summary = f"{done} promote {data.get('release_branch', '')} → main (v{ver}, PR #{pr})"
        else:
            summary = "?"
        print(f"  {data.get('id', p.stem):<32}  {flow:<4}  {ts:<20}  {summary}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand: show
# ─────────────────────────────────────────────────────────────────────────────

def cmd_show(args: argparse.Namespace) -> None:
    path = resolve_snapshot(args.ref)
    if not path:
        print(f"✗ No snapshot matches: {args.ref}")
        raise SystemExit(1)
    data = load_snapshot(path)
    print(f"\n  File: {path}")
    print(json.dumps(data, indent=2))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand: snapshot (manual)
# ─────────────────────────────────────────────────────────────────────────────

def cmd_snapshot(args: argparse.Namespace) -> None:
    gh_bot, _, owner, repo, _ = _get_github_client()
    cfg = load_config()
    if args.flow == "A":
        base = cfg.git.effective_pr_target
        path = create_flow_a_snapshot(gh_bot, owner, repo, base, planned_prs=[])
        print(f"  ✓ Flow A snapshot saved: {path}")
        print(f"    base_branch = {base}")
    elif args.flow == "B":
        version = args.version or cfg.build.nuget_version
        release_branch = args.release_branch or cfg.git.effective_pr_target
        path = create_flow_b_snapshot(gh_bot, owner, repo, release_branch, version)
        print(f"  ✓ Flow B snapshot saved: {path}")
        print(f"    release_branch = {release_branch}")
        print(f"    new_version    = {version}")
    else:
        print("✗ --flow must be A or B")
        raise SystemExit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand: revert-flow-a
# ─────────────────────────────────────────────────────────────────────────────

def cmd_revert_flow_a(args: argparse.Namespace) -> None:
    path = resolve_snapshot(args.ref)
    if not path:
        print(f"✗ No snapshot matches: {args.ref}")
        raise SystemExit(1)
    data = load_snapshot(path)
    if data.get("flow") != "A":
        print(f"✗ {path} is not a Flow A snapshot (flow={data.get('flow')})")
        raise SystemExit(1)

    gh_bot, _, owner, repo, local = _get_github_client()
    base = data["base_branch"]
    base_sha_before = data.get("base_sha_before", "")
    merged_prs = data.get("merged_prs", [])

    if not merged_prs:
        print("  Snapshot has no merged PRs recorded — nothing to revert.")
        return

    print(f"\n  Rollback plan for Flow A snapshot {data.get('id')}")
    print(f"  {'=' * 60}")
    print(f"  Base branch:       {base}")
    print(f"  Tip before merge:  {base_sha_before[:7] if base_sha_before else '(unknown)'}")
    print(f"  PRs merged:        {len(merged_prs)}")
    for entry in merged_prs:
        print(f"    - #{entry.get('pr_number')}  ({entry.get('reason', '')})")
    print(f"\n  Action:            walk merge commits on {base} newer than the")
    print(f"                     snapshot tip, revert each via `git revert -m 1`,")
    print(f"                     push a revert branch, and open a revert PR.")

    if not _confirm("Proceed with revert?", args.yes):
        return

    # ── 1. Sync local repo ──
    print(f"\n  → fetching origin...")
    _run_git(["fetch", "origin", "--prune"], local)
    _require_clean_worktree(local)

    # Make sure the snapshot SHA is reachable locally
    if base_sha_before:
        check = _run_git(["cat-file", "-e", base_sha_before], local, check=False)
        if check.returncode != 0:
            print(f"  ✗ snapshot SHA {base_sha_before[:7]} is not in local repo")
            print(f"    try: git fetch origin {base} --unshallow")
            raise SystemExit(1)

    # ── 2. Find merge commits to revert ──
    range_spec = f"{base_sha_before}..origin/{base}" if base_sha_before else f"origin/{base}"
    log = _run_git(
        ["log", "--merges", "--format=%H|%s", range_spec],
        local,
    )
    merge_lines = [ln for ln in log.stdout.splitlines() if ln.strip()]
    if not merge_lines:
        print(f"  No merge commits found on {base} newer than snapshot — nothing to revert.")
        return

    merged_pr_numbers = {entry.get("pr_number") for entry in merged_prs}
    merges_to_revert: list[tuple[str, str]] = []
    for ln in merge_lines:
        sha, subject = ln.split("|", 1)
        # Try to match "Merge pull request #N from ..."
        pr_num = None
        if "#" in subject:
            token = subject.split("#", 1)[1].split()[0].rstrip(":,.")
            if token.isdigit():
                pr_num = int(token)
        if pr_num is None or pr_num in merged_pr_numbers:
            merges_to_revert.append((sha, subject))

    if not merges_to_revert:
        print("  No matching merge commits to revert.")
        return

    print(f"\n  Found {len(merges_to_revert)} merge commit(s) to revert:")
    for sha, subj in merges_to_revert:
        print(f"    {sha[:7]}  {subj[:60]}")

    # ── 3. Create revert branch off origin/base ──
    revert_branch = f"rollback/flow-a-{data.get('id')}"
    print(f"\n  → creating {revert_branch} from origin/{base}...")
    _run_git(["checkout", "-B", revert_branch, f"origin/{base}"], local)

    # ── 4. Revert each merge commit (newest first) ──
    for sha, subj in merges_to_revert:
        print(f"  → git revert -m 1 {sha[:7]} ({subj[:50]})")
        r = _run_git(["revert", "-m", "1", "--no-edit", sha], local, check=False)
        if r.returncode != 0:
            print("  ✗ revert failed — resolve conflicts manually, then:")
            print(f"       cd {local}")
            print( "       git revert --continue")
            print(f"       git push -u origin {revert_branch}")
            print(f"  Then open a revert PR manually into {base}.")
            raise SystemExit(1)

    # ── 5. Push + open revert PR ──
    print(f"\n  → pushing {revert_branch}...")
    _run_git(["push", "-u", "origin", revert_branch], local)

    title = f"Rollback: revert {len(merges_to_revert)} PR(s) from {base}"
    body = (
        f"Automated rollback for Flow A snapshot `{data.get('id')}`.\n\n"
        f"Reverted merges:\n"
        + "\n".join(f"- {sha[:7]} {subj}" for sha, subj in merges_to_revert)
        + f"\n\nSnapshot file: `rollback_snapshots/{path.name}`\n"
    )
    pr_url = gh_bot.create_pull_request(owner, repo, title, body, revert_branch, base)
    if pr_url:
        print(f"\n  ✓ Revert PR created: {pr_url}")
    else:
        print("\n  ✗ PR creation failed — open manually via GitHub.")


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand: revert-flow-b
# ─────────────────────────────────────────────────────────────────────────────

def cmd_revert_flow_b(args: argparse.Namespace) -> None:
    path = resolve_snapshot(args.ref)
    if not path:
        print(f"✗ No snapshot matches: {args.ref}")
        raise SystemExit(1)
    data = load_snapshot(path)
    if data.get("flow") != "B":
        print(f"✗ {path} is not a Flow B snapshot (flow={data.get('flow')})")
        raise SystemExit(1)

    gh_bot, _, owner, repo, local = _get_github_client()

    main_sha_before = data.get("main_sha_before", "")
    main_sha_after = data.get("main_sha_after", "")
    new_tag = data.get("new_tag", "")
    env_before = data.get("env_before", {}) or {}
    pr_number = data.get("pr_number")

    print(f"\n  Rollback plan for Flow B snapshot {data.get('id')}")
    print(f"  {'=' * 60}")
    print(f"  main before:  {main_sha_before[:7] if main_sha_before else '(unknown)'}")
    print(f"  main after:   {main_sha_after[:7] if main_sha_after else '(unknown)'}")
    print(f"  PR:           #{pr_number if pr_number else '?'}")
    print(f"  New tag:      {new_tag}")
    print( "\n  Actions:")
    print(f"    1. Create revert PR for squash commit on main")
    print(f"    2. Delete GitHub Release for {new_tag}")
    print(f"    3. Delete tag {new_tag}")
    print(f"    4. Print .env restore instructions")

    if not _confirm("Proceed with revert?", args.yes):
        return

    # ── 1. Revert squash commit on main ──
    if main_sha_after:
        print(f"\n  → fetching origin...")
        _run_git(["fetch", "origin", "--prune"], local)
        _require_clean_worktree(local)

        check = _run_git(["cat-file", "-e", main_sha_after], local, check=False)
        if check.returncode != 0:
            print(f"  ✗ squash commit {main_sha_after[:7]} not in local repo; try git fetch")
            raise SystemExit(1)

        revert_branch = f"rollback/flow-b-{data.get('id')}"
        print(f"  → creating {revert_branch} from origin/main...")
        _run_git(["checkout", "-B", revert_branch, "origin/main"], local)
        print(f"  → git revert {main_sha_after[:7]}")
        r = _run_git(["revert", "--no-edit", main_sha_after], local, check=False)
        if r.returncode != 0:
            print("  ✗ revert failed — resolve conflicts, then continue manually.")
            raise SystemExit(1)
        _run_git(["push", "-u", "origin", revert_branch], local)

        title = f"Rollback: revert promotion of v{data.get('new_version', '?')} to main"
        body = (
            f"Automated rollback for Flow B snapshot `{data.get('id')}`.\n\n"
            f"Reverts squash commit `{main_sha_after}` "
            f"(promotion PR #{pr_number}).\n\n"
            f"Snapshot file: `rollback_snapshots/{path.name}`\n"
        )
        pr_url = gh_bot.create_pull_request(owner, repo, title, body, revert_branch, "main")
        if pr_url:
            print(f"  ✓ Revert PR created: {pr_url}")
        else:
            print("  ✗ PR creation failed — open manually.")
    else:
        print("  ⚠ No main_sha_after recorded — skipping main revert.")

    # ── 2. Delete GitHub Release ──
    if new_tag:
        print(f"\n  → deleting GitHub Release {new_tag}...")
        if gh_bot.delete_release(owner, repo, new_tag):
            print(f"  ✓ Release {new_tag} deleted (or was absent)")
        else:
            print(f"  ⚠ Could not delete release {new_tag} — remove via GitHub UI.")

    # ── 3. Delete tag ──
    if new_tag:
        print(f"  → deleting tag {new_tag}...")
        if gh_bot.delete_tag(owner, repo, new_tag):
            print(f"  ✓ Tag {new_tag} deleted (or was absent)")
        else:
            print(f"  ⚠ Could not delete tag {new_tag} — remove via GitHub UI.")

    # ── 4. Print .env restore instructions ──
    print("\n  ┌─ .env restore (manual) ─────────────────────────────────")
    if env_before:
        for k, v in env_before.items():
            print(f"  │  {k}={v}")
    else:
        print("  │  (no env_before captured)")
    print("  └──────────────────────────────────────────────────────────")
    print("  After editing .env, restart uvicorn to pick up the old version.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Argparse setup
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rollback",
        description="Rollback CLI for Flow A / Flow B merges and promotions.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List saved snapshots newest-first")
    p_list.add_argument("--flow", choices=("A", "B"), help="Filter by flow")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Print a snapshot's contents")
    p_show.add_argument("ref", help="Snapshot id, file, path, or 'latest[-a|-b]'")
    p_show.set_defaults(func=cmd_show)

    p_snap = sub.add_parser("snapshot", help="Capture a manual pre-flight snapshot")
    p_snap.add_argument("--flow", choices=("A", "B"), required=True)
    p_snap.add_argument("--version", help="New version (flow B only)")
    p_snap.add_argument("--release-branch", help="Release branch (flow B only)")
    p_snap.set_defaults(func=cmd_snapshot)

    p_ra = sub.add_parser(
        "revert-flow-a",
        help="Revert all merges made by a Flow A run (creates a revert PR)",
    )
    p_ra.add_argument("ref", help="Snapshot id, file, path, or 'latest-a'")
    p_ra.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    p_ra.set_defaults(func=cmd_revert_flow_a)

    p_rb = sub.add_parser(
        "revert-flow-b",
        help="Revert a Flow B promotion (creates a revert PR, deletes tag/release)",
    )
    p_rb.add_argument("ref", help="Snapshot id, file, path, or 'latest-b'")
    p_rb.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    p_rb.set_defaults(func=cmd_revert_flow_b)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
