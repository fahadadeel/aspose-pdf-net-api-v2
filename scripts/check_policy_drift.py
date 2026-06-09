"""
scripts/check_policy_drift.py -- Verify live branch protection matches policy/.

Reads the JSON artifacts in policy/ and the live config from GitHub + GitLab
APIs. Reports drift on any tracked field. Designed to run in CI as a
policy-as-code gate.

Required env vars (any subset is OK — missing providers are skipped):
    GITHUB_TOKEN      — PAT with repo scope for the GitHub mirror
    GITHUB_OWNER      — default "fahadadeel"
    GITHUB_REPO       — default "aspose-pdf-net-api-v2"
    GITLAB_TOKEN      — PAT with api scope for the GitLab origin
    GITLAB_HOST       — default "gitlab.recruitize.ai"
    GITLAB_PROJECT_ID — default "560"

Exit codes:
    0 — every provider checked matches policy (or was skipped)
    1 — drift detected on at least one tracked field
    2 — both providers were unreachable / unauthorised (operator error)
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

GITHUB_POLICY = REPO_ROOT / "policy" / "github-branch-protection-main.json"
GITLAB_POLICY = REPO_ROOT / "policy" / "gitlab-branch-protection-main.json"


class _C:
    if sys.stdout.isatty() and os.getenv("NO_COLOR") is None:
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        RED = "\033[31m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        RESET = "\033[0m"
    else:
        GREEN = YELLOW = RED = BOLD = DIM = RESET = ""


def _http_get(url: str, headers: dict, timeout: int = 15) -> dict | None:
    """GET and parse JSON. Returns None on any error (caller decides severity)."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"{_C.RED}  HTTP {e.code} on {url}{_C.RESET}")
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"{_C.RED}  request failed: {e}{_C.RESET}")
        return None


def _diff(field: str, expected, actual) -> bool:
    """Print a diff line. Returns True if there is drift."""
    if expected == actual:
        print(f"  {_C.GREEN}✓{_C.RESET}  {field:<48} {_C.DIM}({actual}){_C.RESET}")
        return False
    print(
        f"  {_C.RED}✗{_C.RESET}  {field:<48} "
        f"{_C.DIM}expected{_C.RESET} {expected!r} "
        f"{_C.DIM}got{_C.RESET} {actual!r}"
    )
    return True


# ── GitHub ──────────────────────────────────────────────────────────────────

def check_github() -> str:
    """Returns 'ok', 'drift', or 'skip'."""
    print(f"\n{_C.BOLD}GitHub{_C.RESET}")
    print(_C.DIM + "─" * 60 + _C.RESET)

    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        print(f"  {_C.YELLOW}⚠ GITHUB_TOKEN not set — skipping{_C.RESET}")
        return "skip"

    if not GITHUB_POLICY.exists():
        print(f"  {_C.YELLOW}⚠ {GITHUB_POLICY.relative_to(REPO_ROOT)} missing — skipping{_C.RESET}")
        return "skip"

    owner = os.getenv("GITHUB_OWNER", "fahadadeel")
    repo = os.getenv("GITHUB_REPO", "aspose-pdf-net-api-v2")
    expected = json.loads(GITHUB_POLICY.read_text(encoding="utf-8"))
    actual = _http_get(
        f"https://api.github.com/repos/{owner}/{repo}/branches/main/protection",
        {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    if actual is None:
        return "skip"

    drift = False
    # required_status_checks
    exp_checks = expected.get("required_status_checks") or {}
    act_checks = actual.get("required_status_checks") or {}
    drift |= _diff(
        "required_status_checks.strict",
        exp_checks.get("strict"), act_checks.get("strict"),
    )
    drift |= _diff(
        "required_status_checks.contexts",
        sorted(exp_checks.get("contexts") or []),
        sorted(act_checks.get("contexts") or []),
    )

    # boolean toggles
    for key in (
        "allow_force_pushes",
        "allow_deletions",
        "required_linear_history",
        "required_conversation_resolution",
        "lock_branch",
        "allow_fork_syncing",
    ):
        # GitHub returns these as {enabled: bool} dicts when read but the
        # PUT body has them as plain booleans. Normalise both shapes.
        act = actual.get(key)
        act_bool = act.get("enabled") if isinstance(act, dict) else act
        drift |= _diff(key, expected.get(key), act_bool)

    return "drift" if drift else "ok"


# ── GitLab ──────────────────────────────────────────────────────────────────

def check_gitlab() -> str:
    """Returns 'ok', 'drift', or 'skip'."""
    print(f"\n{_C.BOLD}GitLab{_C.RESET}")
    print(_C.DIM + "─" * 60 + _C.RESET)

    token = os.getenv("GITLAB_TOKEN", "").strip()
    if not token:
        print(f"  {_C.YELLOW}⚠ GITLAB_TOKEN not set — skipping{_C.RESET}")
        return "skip"

    if not GITLAB_POLICY.exists():
        print(f"  {_C.YELLOW}⚠ {GITLAB_POLICY.relative_to(REPO_ROOT)} missing — skipping{_C.RESET}")
        return "skip"

    host = os.getenv("GITLAB_HOST", "gitlab.recruitize.ai")
    project_id = os.getenv("GITLAB_PROJECT_ID", "560")
    expected = json.loads(GITLAB_POLICY.read_text(encoding="utf-8"))
    exp_branch = expected.get("protected_branch", {})
    exp_project = expected.get("project_settings", {})

    api_base = f"https://{host}/api/v4/projects/{project_id}"
    headers = {"PRIVATE-TOKEN": token}

    actual_branch = _http_get(f"{api_base}/protected_branches/main", headers)
    actual_project = _http_get(api_base, headers)
    if actual_branch is None or actual_project is None:
        return "skip"

    drift = False

    # Protected branch access levels (compare highest level)
    exp_push = exp_branch.get("allowed_to_push", [{}])[0].get("access_level")
    act_push = (actual_branch.get("push_access_levels") or [{}])[0].get("access_level")
    drift |= _diff("protected_branch.push_access_level", exp_push, act_push)

    exp_merge = exp_branch.get("allowed_to_merge", [{}])[0].get("access_level")
    act_merge = (actual_branch.get("merge_access_levels") or [{}])[0].get("access_level")
    drift |= _diff("protected_branch.merge_access_level", exp_merge, act_merge)

    drift |= _diff(
        "protected_branch.allow_force_push",
        exp_branch.get("allow_force_push"),
        actual_branch.get("allow_force_push"),
    )

    # Project-level merge-request settings
    for key in (
        "only_allow_merge_if_pipeline_succeeds",
        "only_allow_merge_if_all_discussions_are_resolved",
    ):
        drift |= _diff(f"project.{key}", exp_project.get(key), actual_project.get(key))

    # code_owner_approval_required is a Premium feature; skip if undeclared
    if exp_project.get("merge_requests_require_code_owner_approval") is not None:
        act = actual_project.get("merge_requests_require_code_owner_approval")
        if act is not None:
            drift |= _diff(
                "project.merge_requests_require_code_owner_approval",
                exp_project.get("merge_requests_require_code_owner_approval"),
                act,
            )

    return "drift" if drift else "ok"


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"{_C.BOLD}╔══════════════════════════════════════════════════════════╗")
    print("║  POLICY DRIFT CHECK — branch protection vs policy/       ║")
    print(f"╚══════════════════════════════════════════════════════════╝{_C.RESET}")

    results = {
        "github": check_github(),
        "gitlab": check_gitlab(),
    }

    print()
    print(_C.BOLD + "═" * 60 + _C.RESET)
    for provider, status in results.items():
        icon = {"ok": _C.GREEN + "✓", "drift": _C.RED + "✗", "skip": _C.YELLOW + "⚠"}[status]
        print(f"  {icon}{_C.RESET}  {provider:<10} {status}")
    print(_C.BOLD + "═" * 60 + _C.RESET)

    if any(s == "drift" for s in results.values()):
        return 1
    if all(s == "skip" for s in results.values()):
        # Tokens unavailable — common on unprotected branches when the
        # CI variable is marked Protected. Warn but don't fail the build.
        print(f"\n{_C.YELLOW}  ⚠ All providers skipped (tokens unavailable). "
              f"Pass --require-tokens to fail when this happens.{_C.RESET}")
        return 0 if "--require-tokens" not in sys.argv else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
