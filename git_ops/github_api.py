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
