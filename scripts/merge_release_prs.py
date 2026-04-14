"""
scripts/merge_release_prs.py — Flow A helpers.

Fetch, update, and merge bot-authored PRs targeting the release branch
via the GitHub API. Update Branch is called with the bot token (the bot
owns the branch); the final merge uses the merge-acct token so the
commit is attributed to a human reviewer on the GitHub timeline.

Pure functions — no classes, no side effects beyond the GitHub calls
and stdout/log_fn output. Reusable from both the `parallel_run.py` CLI
and ad-hoc scripts.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable, Optional

from git_ops.github_api import GitHubAPI


# ── Ready-to-merge mergeable_state values ──
# See https://docs.github.com/en/graphql/reference/enums#mergestatestatus
# - clean     : CI passed, no conflicts
# - unstable  : non-required checks failed but PR is still mergeable
# - behind    : PR branch is behind base — needs Update Branch
# - has_hooks : mergeable, hooks configured
_MERGEABLE_STATES = {"clean", "unstable", "behind", "has_hooks"}


def fetch_mergeable_prs(
    gh: GitHubAPI,
    owner: str,
    repo: str,
    base_branch: str,
    bot_login: Optional[str] = None,
) -> list[dict]:
    """Return PRs ready to merge into base_branch.

    Filters:
      - open, base == base_branch
      - (optional) authored by bot_login
      - mergeable_state in {clean, unstable, behind, has_hooks}
      - current CI state is 'success' or 'unknown'
        ('unknown' = no checks yet, e.g. docs-only PR — still eligible)

    Each returned dict has:
      number, title, head_sha, head_ref, mergeable_state, ci_state,
      html_url, user_login.
    """
    raw = gh.list_open_prs(owner, repo, base_branch, author=bot_login)
    results: list[dict] = []
    for pr in raw:
        number = pr.get("number")
        if not number:
            continue
        # list endpoint doesn't populate mergeable/mergeable_state reliably,
        # so hit the per-PR endpoint for accurate values.
        detail = gh.get_pull_request(owner, repo, number) or {}
        state = detail.get("mergeable_state") or ""
        if state not in _MERGEABLE_STATES:
            continue

        head = detail.get("head") or {}
        head_sha = head.get("sha", "")
        head_ref = head.get("ref", "")
        if not head_sha:
            continue

        ci = gh.get_combined_check_status(owner, repo, head_sha)
        ci_state = ci.get("state", "unknown")
        # Treat 'unknown' as eligible — caller will re-check after Update Branch.
        if ci_state not in ("success", "unknown"):
            continue

        results.append({
            "number": number,
            "title": detail.get("title", ""),
            "head_sha": head_sha,
            "head_ref": head_ref,
            "mergeable_state": state,
            "ci_state": ci_state,
            "html_url": detail.get("html_url", ""),
            "user_login": (detail.get("user") or {}).get("login", ""),
        })
    return results


def print_merge_plan(prs: list[dict], base_branch: str) -> None:
    """Print a compact merge plan table."""
    if not prs:
        print(f"\n  No PRs ready to merge into {base_branch}.\n")
        return

    print(f"\n  Merge plan → {base_branch}  ({len(prs)} PR{'s' if len(prs) != 1 else ''}):\n")
    print(f"    {'#':>3}  {'PR':>5}  {'CI':<8}  {'State':<10}  Title")
    print(f"    {'-'*3}  {'-'*5}  {'-'*8}  {'-'*10}  {'-'*40}")
    for i, pr in enumerate(prs, 1):
        title = (pr.get("title") or "")[:60]
        print(f"    {i:>3}  #{pr['number']:<4}  {pr['ci_state']:<8}  {pr['mergeable_state']:<10}  {title}")
    print()


def process_one_pr(
    gh_bot: GitHubAPI,
    gh_personal: GitHubAPI,
    owner: str,
    repo: str,
    pr: dict,
    ci_timeout: int = 900,
    log_fn: Callable[[str], None] = print,
) -> dict:
    """Orchestrate one PR: Update Branch → wait CI → Merge.

    Returns {pr_number, status, reason, elapsed}.
    status is one of: 'merged', 'skipped', 'failed'.
    """
    pr_number = pr["number"]
    head_sha = pr["head_sha"]
    state = pr["mergeable_state"]
    start = time.monotonic()

    def _result(status: str, reason: str) -> dict:
        return {
            "pr_number": pr_number,
            "status": status,
            "reason": reason,
            "elapsed": round(time.monotonic() - start, 1),
        }

    # ── Step 1: Update Branch if behind (bot token owns the branch) ──
    if state == "behind":
        log_fn(f"  PR #{pr_number}: updating branch from base...")
        if not gh_bot.update_pr_branch(owner, repo, pr_number, head_sha):
            return _result("skipped", "update_branch failed (conflict?)")

        # After Update Branch, the PR gets a new head SHA. Re-fetch.
        time.sleep(3)
        detail = gh_bot.get_pull_request(owner, repo, pr_number)
        if not detail:
            return _result("failed", "could not re-fetch PR after update_branch")
        head_sha = (detail.get("head") or {}).get("sha", "") or head_sha
        log_fn(f"  PR #{pr_number}: new head {head_sha[:7]}, waiting for CI...")
    else:
        log_fn(f"  PR #{pr_number}: already up to date, checking CI...")

    # ── Step 2: Wait for CI on the (possibly new) head SHA ──
    ci_state = gh_bot.wait_for_checks(
        owner, repo, head_sha,
        timeout=ci_timeout,
        poll_interval=10,
        log_fn=lambda m: log_fn(f"  PR #{pr_number}: {m}"),
    )
    if ci_state == "failure":
        return _result("skipped", "CI failed")
    if ci_state == "timeout":
        return _result("skipped", f"CI timeout after {ci_timeout}s")
    # success or unknown (no checks reported) → proceed

    # ── Step 3: Merge using the personal token (human attribution) ──
    log_fn(f"  PR #{pr_number}: merging (as merge-acct)...")
    ok = gh_personal.merge_pull_request(
        owner, repo, pr_number,
        commit_message="",
        merge_method="merge",  # merge commit — plays well with HEAD^2 filter
    )
    if not ok:
        return _result("failed", "merge API call failed")
    return _result("merged", "ok")


def run_merge_batch(
    prs: list[dict],
    gh_bot: GitHubAPI,
    gh_personal: GitHubAPI,
    owner: str,
    repo: str,
    ci_timeout: int = 900,
    log_fn: Callable[[str], None] = print,
) -> dict:
    """Sequentially process every PR. Accumulate and return summary."""
    merged = 0
    skipped = 0
    failed = 0
    details: list[dict] = []

    total = len(prs)
    for i, pr in enumerate(prs, 1):
        log_fn(f"\n  [{i}/{total}] PR #{pr['number']}: {pr.get('title', '')[:60]}")
        result = process_one_pr(gh_bot, gh_personal, owner, repo, pr,
                                 ci_timeout=ci_timeout, log_fn=log_fn)
        details.append(result)
        status = result["status"]
        if status == "merged":
            merged += 1
            log_fn(f"  PR #{pr['number']}: ✓ merged ({result['elapsed']}s)")
        elif status == "skipped":
            skipped += 1
            log_fn(f"  PR #{pr['number']}: ⏭ skipped — {result['reason']}")
        else:
            failed += 1
            log_fn(f"  PR #{pr['number']}: ✗ failed — {result['reason']}")

    return {
        "merged": merged,
        "skipped": skipped,
        "failed": failed,
        "details": details,
    }


def filter_by_numbers(prs: list[dict], wanted: Iterable) -> list[dict]:
    """Filter a PR list to only those whose number is in *wanted*.

    *wanted* may contain ints or strings like '192' / '#192'.
    """
    nums = set()
    for w in wanted:
        s = str(w).lstrip("#").strip()
        if s.isdigit():
            nums.add(int(s))
    if not nums:
        return prs
    return [p for p in prs if p["number"] in nums]
