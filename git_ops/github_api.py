"""
git_ops/github_api.py — GitHub REST API wrapper.

Low-level functions for file CRUD and PR management via the GitHub API.
"""

import base64
from typing import Optional

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
                           commit_message: str = "") -> bool:
        """Merge a pull request via GitHub API. Returns True on success."""
        try:
            payload = {"merge_method": "merge"}
            if commit_message:
                payload["commit_message"] = commit_message
            r = self._session.put(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/merge",
                headers=self._headers,
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                return True
            error_msg = r.json().get("message", r.text[:200])
            print(f"[GitHub] PR merge failed ({r.status_code}): {error_msg}")
            return False
        except Exception as e:
            print(f"[GitHub] Error merging PR: {e}")
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
