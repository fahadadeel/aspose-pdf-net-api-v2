"""
git_ops/github_api.py — GitHub REST API wrapper.

Low-level functions for file CRUD and PR management via the GitHub API.
"""

import base64
import time
from typing import Callable, Optional

import requests


class GitHubAPI:
    """Thin wrapper around GitHub REST API v3."""

    def __init__(self, token: str, session: requests.Session = None):
        self.token = token
        self._session = session or requests.Session()
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get_file(self, owner: str, repo: str, path: str, branch: str) -> Optional[dict]:
        """Get file content from GitHub. Returns dict with 'content', 'sha', etc."""
        try:
            r = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
                headers=self._headers,
                params={"ref": branch},
                timeout=10,
            )
            return r.json() if r.status_code == 200 else None
        except Exception as e:
            print(f"[GitHub] Error getting file {path}: {e}")
            return None

    def list_directory(self, owner: str, repo: str, path: str, branch: str) -> list:
        """List files in a directory on a branch. Returns list of entry dicts (name, type, path)."""
        try:
            r = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
                headers=self._headers,
                params={"ref": branch},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return data
            return []
        except Exception as e:
            print(f"[GitHub] Error listing directory {path}: {e}")
            return []

    def list_branch_cs_files(self, owner: str, repo: str, branch: str) -> dict:
        """List all .cs files on a branch grouped by category folder.

        Returns {category_slug: [filename, ...]} by listing the repo root
        and recursing one level into each directory.
        """
        result = {}
        root_entries = self.list_directory(owner, repo, "", branch)
        for entry in root_entries:
            if entry.get("type") != "dir":
                continue
            cat_slug = entry["name"]
            if cat_slug.startswith(".") or cat_slug in ("docs", ".github"):
                continue
            files = self.list_directory(owner, repo, cat_slug, branch)
            cs_files = [f["name"] for f in files if f.get("name", "").endswith(".cs")]
            if cs_files:
                result[cat_slug] = cs_files
        return result

    def list_branch_category_status(self, owner: str, repo: str, branch: str) -> dict:
        """List all categories on a branch with .cs file count and sidecar presence.

        Returns {category_slug: {"cs_count": int, "has_agents_md": bool, "has_index_json": bool}}
        """
        result = {}
        root_entries = self.list_directory(owner, repo, "", branch)
        for entry in root_entries:
            if entry.get("type") != "dir":
                continue
            cat_slug = entry["name"]
            if cat_slug.startswith(".") or cat_slug in ("docs", ".github"):
                continue
            files = self.list_directory(owner, repo, cat_slug, branch)
            file_names = [f.get("name", "") for f in files]
            cs_count = sum(1 for n in file_names if n.endswith(".cs"))
            if cs_count > 0 or "agents.md" in file_names or "index.json" in file_names:
                result[cat_slug] = {
                    "cs_count": cs_count,
                    "has_agents_md": "agents.md" in file_names,
                    "has_index_json": "index.json" in file_names,
                }
        return result

    def create_or_update_file(
        self, owner: str, repo: str, path: str,
        content: str, message: str, branch: str,
        sha: Optional[str] = None,
    ) -> bool:
        """Create or update a file via GitHub API."""
        try:
            payload = {
                "message": message,
                "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha

            r = self._session.put(
                f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
                headers=self._headers,
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                return True
            error_msg = r.json().get("message", r.text[:200])
            print(f"[GitHub] Failed to create/update {path}: {error_msg}")
            return False
        except Exception as e:
            print(f"[GitHub] Error creating/updating {path}: {e}")
            return False

    def create_pull_request(
        self, owner: str, repo: str,
        title: str, body: str,
        head: str, base: str,
    ) -> Optional[str]:
        """Create a GitHub PR. Returns html_url or None."""
        try:
            r = self._session.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers=self._headers,
                json={"title": title, "body": body, "head": head, "base": base},
                timeout=15,
            )
            if r.status_code in (200, 201):
                return r.json().get("html_url", "")
            if r.status_code == 422:
                existing = self.find_existing_pr(owner, repo, head, base)
                if existing:
                    return existing
            error_msg = r.json().get("message", r.text[:200])
            print(f"[GitHub] PR creation failed ({r.status_code}): {error_msg}")
            return None
        except Exception as e:
            print(f"[GitHub] PR creation error: {e}")
            return None

    def get_branch_sha(self, owner: str, repo: str, branch: str) -> Optional[str]:
        """Get the latest commit SHA for a branch."""
        try:
            r = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{branch}",
                headers=self._headers,
                timeout=10,
            )
            if r.status_code == 200:
                return r.json()["object"]["sha"]
            return None
        except Exception as e:
            print(f"[GitHub] Error getting branch SHA: {e}")
            return None

    def create_branch(self, owner: str, repo: str, branch: str, from_sha: str) -> bool:
        """Create a new branch from a commit SHA."""
        try:
            r = self._session.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs",
                headers=self._headers,
                json={"ref": f"refs/heads/{branch}", "sha": from_sha},
                timeout=10,
            )
            if r.status_code in (200, 201):
                return True
            error_msg = r.json().get("message", r.text[:200])
            print(f"[GitHub] Branch creation failed: {error_msg}")
            return False
        except Exception as e:
            print(f"[GitHub] Error creating branch: {e}")
            return False

    def find_existing_pr(self, owner: str, repo: str, head: str, base: str) -> Optional[str]:
        """Find an open PR for head->base. Returns html_url or None."""
        try:
            r = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers=self._headers,
                params={"head": f"{owner}:{head}", "base": base, "state": "open"},
                timeout=10,
            )
            if r.status_code == 200:
                pulls = r.json()
                if pulls:
                    return pulls[0].get("html_url", "")
        except Exception as e:
            print(f"[GitHub] Could not look up existing PR: {e}")
        return None

    def tag_exists(self, owner: str, repo: str, tag_name: str) -> bool:
        """Check whether a tag ref already exists on the remote."""
        try:
            r = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/ref/tags/{tag_name}",
                headers=self._headers,
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def force_update_ref(self, owner: str, repo: str, ref: str, sha: str) -> bool:
        """Force-update a branch ref to a new SHA (e.g. point main at a different commit)."""
        try:
            r = self._session.patch(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{ref}",
                headers=self._headers,
                json={"sha": sha, "force": True},
                timeout=10,
            )
            if r.status_code == 200:
                return True
            error_msg = r.json().get("message", r.text[:200])
            print(f"[GitHub] Force-update ref failed ({r.status_code}): {error_msg}")
            return False
        except Exception as e:
            print(f"[GitHub] Error force-updating ref: {e}")
            return False

    def create_tag(self, owner: str, repo: str, tag_name: str, sha: str, message: str = "") -> bool:
        """Create a lightweight tag via GitHub API."""
        try:
            r = self._session.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs",
                headers=self._headers,
                json={"ref": f"refs/tags/{tag_name}", "sha": sha},
                timeout=10,
            )
            if r.status_code in (200, 201):
                return True
            error_msg = r.json().get("message", r.text[:200])
            print(f"[GitHub] Tag creation failed: {error_msg}")
            return False
        except Exception as e:
            print(f"[GitHub] Error creating tag: {e}")
            return False

    def create_release(
        self, owner: str, repo: str,
        tag_name: str, name: str, body: str = "",
    ) -> Optional[str]:
        """Create a GitHub Release from a tag. Returns html_url or None."""
        try:
            r = self._session.post(
                f"https://api.github.com/repos/{owner}/{repo}/releases",
                headers=self._headers,
                json={
                    "tag_name": tag_name,
                    "name": name,
                    "body": body,
                    "draft": False,
                    "prerelease": False,
                },
                timeout=15,
            )
            if r.status_code in (200, 201):
                return r.json().get("html_url", "")
            error_msg = r.json().get("message", r.text[:200])
            print(f"[GitHub] Release creation failed: {error_msg}")
            return None
        except Exception as e:
            print(f"[GitHub] Error creating release: {e}")
            return None

    def create_empty_branch(self, owner: str, repo: str, branch: str,
                            log_fn=None) -> bool:
        """Create an orphan branch (no parent commits) via GitHub Git Data API.

        Uses a minimal tree with a .gitkeep placeholder — empty trees are
        rejected by the GitHub API. Accepts an optional log_fn(msg) callback
        so callers can route error messages to their own logging system.
        """
        def _log(msg: str):
            if log_fn:
                log_fn(msg)
            print(msg)

        try:
            # 1. Create a minimal tree with a .gitkeep blob (empty trees fail on GitHub)
            tree_r = self._session.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/trees",
                headers=self._headers,
                json={"tree": [
                    {"path": ".gitkeep", "mode": "100644", "type": "blob", "content": ""}
                ]},
                timeout=10,
            )
            if tree_r.status_code not in (200, 201):
                _log(f"[GitHub] Tree creation failed ({tree_r.status_code}): {tree_r.text[:300]}")
                return False
            tree_sha = tree_r.json()["sha"]
            _log(f"[GitHub] Created tree: {tree_sha}")

            # 2. Create orphan commit (no parents)
            commit_r = self._session.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/commits",
                headers=self._headers,
                json={"message": f"Init {branch}", "tree": tree_sha, "parents": []},
                timeout=10,
            )
            if commit_r.status_code not in (200, 201):
                _log(f"[GitHub] Commit creation failed ({commit_r.status_code}): {commit_r.text[:300]}")
                return False
            commit_sha = commit_r.json()["sha"]
            _log(f"[GitHub] Created orphan commit: {commit_sha}")

            # 3. Create branch ref from the orphan commit
            ref_r = self._session.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs",
                headers=self._headers,
                json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
                timeout=10,
            )
            if ref_r.status_code in (200, 201):
                _log(f"[GitHub] Branch ref created: refs/heads/{branch}")
                return True
            error_msg = ref_r.json().get("message", ref_r.text[:200])
            _log(f"[GitHub] Branch ref creation failed ({ref_r.status_code}): {error_msg}")
            return False
        except Exception as e:
            _log(f"[GitHub] Error creating empty branch: {e}")
            return False

    def merge_pull_request(self, owner: str, repo: str, pr_number: int,
                           commit_message: str = "",
                           merge_method: str = "merge") -> bool:
        """Merge a pull request via GitHub API. Returns True on success.

        merge_method: 'merge' (default), 'squash', or 'rebase'.
        """
        try:
            payload = {"merge_method": merge_method}
            if commit_message:
                payload["commit_message"] = commit_message
            r = self._session.put(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/merge",
                headers=self._headers,
                json=payload,
                timeout=30,
            )
            if r.status_code in (200, 201):
                return True
            error_msg = r.json().get("message", r.text[:200])
            print(f"[GitHub] PR merge failed ({r.status_code}): {error_msg}")
            return False
        except Exception as e:
            print(f"[GitHub] Error merging PR: {e}")
            return False

    def list_open_prs(self, owner: str, repo: str, base: str,
                      author: Optional[str] = None) -> list:
        """List open PRs targeting a base branch.

        GET /repos/{owner}/{repo}/pulls?base={base}&state=open

        Returns list of PR dicts (each with number, title, head, user,
        mergeable_state, html_url). If author is given, filters to PRs
        created by that login.
        """
        try:
            prs: list = []
            page = 1
            while True:
                r = self._session.get(
                    f"https://api.github.com/repos/{owner}/{repo}/pulls",
                    headers=self._headers,
                    params={
                        "base": base,
                        "state": "open",
                        "per_page": 100,
                        "page": page,
                    },
                    timeout=15,
                )
                if r.status_code != 200:
                    print(f"[GitHub] list_open_prs failed ({r.status_code}): {r.text[:200]}")
                    return prs
                batch = r.json() or []
                if not batch:
                    break
                prs.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            if author:
                prs = [p for p in prs if (p.get("user") or {}).get("login") == author]
            return prs
        except Exception as e:
            print(f"[GitHub] Error listing open PRs: {e}")
            return []

    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> Optional[dict]:
        """Fetch a single PR (includes mergeable, mergeable_state, head.sha)."""
        try:
            r = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
                headers=self._headers,
                timeout=10,
            )
            if r.status_code == 200:
                return r.json()
            print(f"[GitHub] get_pull_request failed ({r.status_code}): {r.text[:200]}")
            return None
        except Exception as e:
            print(f"[GitHub] Error getting PR #{pr_number}: {e}")
            return None

    def get_combined_check_status(self, owner: str, repo: str, commit_sha: str) -> dict:
        """Combined CI status for a commit.

        Merges the modern check-runs API with the legacy combined status
        API so we don't miss status-posted checks.

        Returns {"state": "success"|"pending"|"failure"|"unknown",
                  "checks": [{"name": str, "conclusion": str}, ...]}

        state is 'success' only when every check-run concludes 'success'
        (or 'neutral'/'skipped') AND the legacy combined status is
        'success' or empty.
        """
        result = {"state": "unknown", "checks": []}
        try:
            r = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}/check-runs",
                headers=self._headers,
                params={"per_page": 100},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"[GitHub] check-runs failed ({r.status_code}): {r.text[:200]}")
                return result
            runs = (r.json() or {}).get("check_runs", [])
        except Exception as e:
            print(f"[GitHub] Error fetching check-runs: {e}")
            return result

        checks = []
        has_pending = False
        has_failure = False
        for run in runs:
            name = run.get("name", "")
            status = run.get("status", "")           # queued|in_progress|completed
            conclusion = run.get("conclusion", "")   # success|failure|neutral|cancelled|skipped|timed_out|action_required
            checks.append({"name": name, "conclusion": conclusion or status})
            if status != "completed":
                has_pending = True
                continue
            if conclusion in ("failure", "cancelled", "timed_out", "action_required"):
                has_failure = True
            # success / neutral / skipped count as green

        # Legacy combined status (for tools that still post statuses)
        try:
            r2 = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}/status",
                headers=self._headers,
                timeout=10,
            )
            if r2.status_code == 200:
                legacy_state = (r2.json() or {}).get("state", "")
                if legacy_state == "pending":
                    has_pending = True
                elif legacy_state == "failure":
                    has_failure = True
                # "success" or "" = OK
        except Exception as e:
            print(f"[GitHub] Error fetching legacy status: {e}")

        if has_failure:
            state = "failure"
        elif has_pending:
            state = "pending"
        elif runs:
            state = "success"
        else:
            state = "unknown"  # no checks reported yet
        result["state"] = state
        result["checks"] = checks
        return result

    def wait_for_checks(self, owner: str, repo: str, commit_sha: str,
                        timeout: int = 900, poll_interval: int = 10,
                        log_fn: Optional[Callable[[str], None]] = None) -> str:
        """Poll get_combined_check_status until a terminal state or timeout.

        Returns 'success', 'failure', or 'timeout'. log_fn(msg) is called
        on each poll so orchestrator dashboards can stream progress.
        """
        def _log(msg: str):
            if log_fn:
                try:
                    log_fn(msg)
                except Exception:
                    pass

        start = time.monotonic()
        last_state = ""
        while True:
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                _log(f"[GitHub] wait_for_checks timed out after {int(elapsed)}s (last state: {last_state or 'unknown'})")
                return "timeout"
            status = self.get_combined_check_status(owner, repo, commit_sha)
            state = status.get("state", "unknown")
            if state != last_state:
                n = len(status.get("checks", []))
                _log(f"[GitHub] checks for {commit_sha[:7]}: {state} ({n} check(s))")
                last_state = state
            if state in ("success", "failure"):
                return state
            # 'pending' or 'unknown' — keep polling
            time.sleep(poll_interval)

    def update_pr_branch(self, owner: str, repo: str, pr_number: int,
                         expected_head_sha: str) -> bool:
        """Trigger GitHub's 'Update branch' for a PR.

        PUT /repos/{owner}/{repo}/pulls/{pr_number}/update-branch

        Returns True on 202 (accepted). Returns False on 422 (merge
        conflict — caller should skip).
        """
        try:
            r = self._session.put(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/update-branch",
                headers={**self._headers, "Accept": "application/vnd.github+json"},
                json={"expected_head_sha": expected_head_sha},
                timeout=30,
            )
            if r.status_code == 202:
                return True
            error_msg = ""
            try:
                error_msg = r.json().get("message", r.text[:200])
            except Exception:
                error_msg = r.text[:200]
            print(f"[GitHub] update_pr_branch failed ({r.status_code}): {error_msg}")
            return False
        except Exception as e:
            print(f"[GitHub] Error updating PR branch: {e}")
            return False

    def create_pr_review(self, owner: str, repo: str, pr_number: int,
                         event: str = "APPROVE", body: str = "") -> bool:
        """Create a PR review.

        POST /repos/{owner}/{repo}/pulls/{pr_number}/reviews

        event: APPROVE | REQUEST_CHANGES | COMMENT
        Used by Flow B so the merge-acct user leaves an explicit
        'approved these changes' review on the bot's PR before merging.
        """
        try:
            payload = {"event": event}
            if body:
                payload["body"] = body
            r = self._session.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                headers=self._headers,
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                return True
            error_msg = ""
            try:
                error_msg = r.json().get("message", r.text[:200])
            except Exception:
                error_msg = r.text[:200]
            print(f"[GitHub] create_pr_review failed ({r.status_code}): {error_msg}")
            return False
        except Exception as e:
            print(f"[GitHub] Error creating PR review: {e}")
            return False

    def get_pr_number(self, owner: str, repo: str, head: str, base: str) -> Optional[int]:
        """Find open PR number for head→base. Returns PR number or None."""
        try:
            r = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers=self._headers,
                params={"head": f"{owner}:{head}", "base": base, "state": "open"},
                timeout=10,
            )
            if r.status_code == 200:
                pulls = r.json()
                if pulls:
                    return pulls[0].get("number")
        except Exception as e:
            print(f"[GitHub] Could not get PR number: {e}")
        return None

    def delete_branch(self, owner: str, repo: str, branch: str) -> bool:
        """Delete a remote branch via GitHub API."""
        try:
            r = self._session.delete(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{branch}",
                headers=self._headers,
                timeout=10,
            )
            return r.status_code == 204
        except Exception as e:
            print(f"[GitHub] Error deleting branch {branch}: {e}")
            return False

    def delete_tag(self, owner: str, repo: str, tag_name: str) -> bool:
        """Delete a git tag ref via GitHub API.

        Note: this only removes the ref, not any GitHub Release pointing
        to the tag. Call delete_release first for a full cleanup.
        """
        try:
            r = self._session.delete(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag_name}",
                headers=self._headers,
                timeout=10,
            )
            if r.status_code == 204:
                return True
            print(f"[GitHub] Tag delete failed ({r.status_code}): {r.text[:200]}")
            return False
        except Exception as e:
            print(f"[GitHub] Error deleting tag {tag_name}: {e}")
            return False

    def get_release_by_tag(self, owner: str, repo: str, tag_name: str) -> Optional[dict]:
        """Look up a GitHub Release by its tag name. Returns release dict or None."""
        try:
            r = self._session.get(
                f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag_name}",
                headers=self._headers,
                timeout=10,
            )
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            print(f"[GitHub] Error fetching release {tag_name}: {e}")
            return None

    def delete_release(self, owner: str, repo: str, tag_name: str) -> bool:
        """Delete a GitHub Release identified by its tag name.

        Does NOT delete the underlying tag — call delete_tag afterwards
        if you want to remove the tag as well.
        """
        release = self.get_release_by_tag(owner, repo, tag_name)
        if not release:
            return True  # nothing to delete
        release_id = release.get("id")
        if not release_id:
            return False
        try:
            r = self._session.delete(
                f"https://api.github.com/repos/{owner}/{repo}/releases/{release_id}",
                headers=self._headers,
                timeout=10,
            )
            if r.status_code == 204:
                return True
            print(f"[GitHub] Release delete failed ({r.status_code}): {r.text[:200]}")
            return False
        except Exception as e:
            print(f"[GitHub] Error deleting release {tag_name}: {e}")
            return False

    @staticmethod
    def decode_base64(encoded: str) -> str:
        """Decode base64-encoded GitHub file content."""
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except Exception:
            return ""

    @staticmethod
    def extract_repo_info(url: str) -> tuple:
        """Extract (owner, repo) from a GitHub URL."""
        url = (url or "").rstrip("/").removesuffix(".git")
        if "github.com/" in url:
            parts = url.split("github.com/")[-1].split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
        return None, None
