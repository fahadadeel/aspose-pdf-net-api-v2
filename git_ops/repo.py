"""
git_ops/repo.py — RepoManager: clone, pull, configure, branch.

All git subprocess calls are serialised via _git_lock.
"""

import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

_git_lock = threading.Lock()

Notify = Callable[[str, str], None]


def _noop(stage: str, msg: str):
    pass


class RepoManager:
    """Manages the local git clone used for committing examples."""

    def __init__(
        self,
        repo_path: str,
        repo_url: str = "",
        repo_branch: str = "main",
        repo_token: str = "",
        repo_user: str = "",
        notify: Notify = None,
    ):
        self.repo_path = repo_path
        self.repo_url = repo_url
        self.repo_branch = repo_branch
        self.repo_token = repo_token
        self.repo_user = repo_user
        self._notify = notify or _noop
        self._ready = False
        self.pr_branch: Optional[str] = None

    @property
    def lock(self):
        return _git_lock

    def ensure_ready(self) -> bool:
        """Clone or pull, configure user, checkout branch. Thread-safe."""
        if self._ready:
            return True

        if not self.repo_path:
            self._notify("git_error", "Git: REPO_PATH not set")
            return False

        with _git_lock:
            repo = Path(self.repo_path)
            if not repo.exists() or not (repo / ".git").exists():
                if not self.repo_url:
                    self._notify("git_error", "Git: Repo not found, REPO_URL not set")
                    return False
                try:
                    self._notify("git_clone_start", "Git: Cloning repository...")
                    repo.parent.mkdir(parents=True, exist_ok=True)
                    clone_url = self.repo_url
                    if self.repo_token and "https://" in clone_url:
                        clone_url = clone_url.replace("https://", f"https://oauth2:{self.repo_token}@")
                    subprocess.run(
                        ["git", "clone", clone_url, self.repo_path],
                        check=True, capture_output=True, text=True,
                    )
                    self._notify("git_clone_success", "Git: Repository cloned")
                except Exception as e:
                    self._notify("git_error", f"Git: Clone failed - {str(e)[:100]}")
                    return False
            else:
                # Fetch all remote refs first so checkout/pull have latest data
                try:
                    subprocess.run(
                        ["git", "fetch", "origin"],
                        cwd=self.repo_path, check=True, capture_output=True, text=True,
                        timeout=30,
                    )
                except Exception:
                    pass  # non-fatal, pull below may still work

                # Checkout target branch BEFORE pulling
                if self.repo_branch:
                    try:
                        subprocess.run(
                            ["git", "checkout", self.repo_branch],
                            cwd=self.repo_path, check=True, capture_output=True, text=True,
                        )
                    except Exception as e:
                        self._notify("git_error", f"Git: Failed to checkout {self.repo_branch}")
                        return False

                # Now pull on the correct branch
                self._notify("git_pull_start", "Git: Pulling latest changes...")
                try:
                    subprocess.run(
                        ["git", "pull"], cwd=self.repo_path,
                        check=True, capture_output=True, text=True,
                    )
                    self._notify("git_pull_success", "Git: Pull successful")
                except Exception as e:
                    self._notify("git_error", f"Git: Pull failed - {str(e)[:100]}")

            # Configure git user
            try:
                subprocess.run(
                    ["git", "config", "user.name", "Aspose-Tester"],
                    cwd=self.repo_path, check=True, capture_output=True, text=True,
                )
                email = self.repo_user or "tester@aspose.local"
                subprocess.run(
                    ["git", "config", "user.email", email],
                    cwd=self.repo_path, check=True, capture_output=True, text=True,
                )
            except Exception:
                pass

        self._ready = True
        return True

    def setup_pr_branch(self, branch_name: str) -> bool:
        """Create and checkout a feature branch from origin/{base}."""
        base = self.repo_branch or "main"
        try:
            with _git_lock:
                self._notify("git_pr_branch", f"Git: Creating branch {branch_name}...")
                subprocess.run(
                    ["git", "fetch", "origin", base],
                    cwd=self.repo_path, check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    ["git", "checkout", "-b", branch_name, f"origin/{base}"],
                    cwd=self.repo_path, check=True, capture_output=True, text=True,
                )
                self.pr_branch = branch_name
                self._notify("git_pr_branch_success", f"Git: Branch {branch_name} created")
                return True
        except Exception as e:
            self._notify("git_error", f"Git: Failed to create branch - {str(e)[:100]}")
            self.pr_branch = None
            return False
