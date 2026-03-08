"""
git_ops/committer.py — CodeCommitter: commit, push, batch operations.

Handles writing code files to the repo, committing, and pushing.
"""

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from git_ops.repo import _git_lock

Notify = Callable[[str, str], None]


def _noop(stage: str, msg: str):
    pass


def slugify(text: str, max_len: int = 100) -> str:
    """Create a safe slug for filenames and folders."""
    if not text or not text.strip():
        return "untitled"
    slug = re.sub(r"\s+", "-", text.strip())
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-._")
    if len(slug) > max_len:
        digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[:max_len-9]}-{digest}"
    return slug or "untitled"


def normalize_category(category: Optional[str], default: str = "uncategorized") -> str:
    """Normalize category name for filesystem path."""
    category = (category or "").strip() or default
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", category)
    safe = safe.strip(". ")
    return safe[:60] if safe else slugify(category, max_len=60)


class CodeCommitter:
    """Commits generated code files to a git repository."""

    def __init__(
        self,
        repo_path: str,
        repo_push: bool = False,
        pr_branch: Optional[str] = None,
        repo_branch: str = "main",
        default_category: str = "uncategorized",
        batch_git: bool = False,
        overwrite: bool = False,
        notify: Notify = None,
        llm_client=None,
    ):
        self.repo_path = repo_path
        self.repo_push = repo_push
        self.pr_branch = pr_branch
        self.repo_branch = repo_branch
        self.default_category = default_category
        self.batch_git = batch_git
        self.overwrite = overwrite
        self._notify = notify or _noop
        self._llm = llm_client
        self._pending_commits: List[dict] = []

    def get_pending_by_category(self) -> dict:
        """Group pending commits by category name.

        Returns ``{category_name: [commit_dicts...]}``.
        """
        groups: dict = {}
        for c in self._pending_commits:
            cat = c.get("category") or self.default_category
            groups.setdefault(cat, []).append(c)
        return groups

    def _build_file_path(self, category: str, task: str) -> Path:
        cat_slug = normalize_category(category, self.default_category)
        filename = f"{slugify(task, max_len=120)}.cs"
        return Path(self.repo_path) / cat_slug / filename

    def _get_versioned_path(self, base_path: Path) -> Path:
        if not base_path.exists():
            return base_path
        stem = base_path.stem
        suffix = base_path.suffix
        parent = base_path.parent
        idx = 2
        while True:
            candidate = parent / f"{stem}__v{idx}{suffix}"
            if not candidate.exists():
                return candidate
            idx += 1

    def commit_code(self, task: str, category: str, code: str) -> None:
        """Write code to repo and commit (or stage for batch)."""
        self._notify("git_workflow_start", "Git: Starting commit workflow...")

        target_path = self._build_file_path(category, task)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists():
            try:
                existing = target_path.read_text(encoding="utf-8")
                if existing == code:
                    self._notify("git_skip", "Git: File already exists (identical)")
                    return
            except Exception:
                pass

            if not self.overwrite:
                target_path = self._get_versioned_path(target_path)

        try:
            self._notify("git_write_start", "Git: Writing code to file...")
            target_path.write_text(code, encoding="utf-8")
            self._notify("git_write_success", "Git: Code written to file")

            if self.batch_git:
                with _git_lock:
                    subprocess.run(
                        ["git", "add", str(target_path)],
                        cwd=self.repo_path, check=True, capture_output=True, text=True,
                    )
                self._pending_commits.append({
                    "path": target_path, "prompt": task, "category": category,
                })
                self._notify("git_staged", f"Git: Staged for batch commit ({len(self._pending_commits)} file(s))")
            else:
                self._commit_and_push(target_path, task, category)
        except Exception as e:
            self._notify("git_error", f"Git: Failed to write file - {str(e)[:100]}")

    def _commit_and_push(self, file_path: Path, task: str, category: str) -> bool:
        """Commit a single file and optionally push."""
        # Generate commit message
        commit_msg = None
        if self._llm:
            try:
                code = file_path.read_text(encoding="utf-8")
                commit_msg = self._llm.generate_commit_message(task, category, code)
            except Exception:
                pass

        if commit_msg and "title" in commit_msg and "description" in commit_msg:
            message = f"{commit_msg['title']}\n\n{commit_msg['description']}"
        else:
            message = f"Add {file_path.parent.name}/{file_path.name} for: {task[:60]}"

        try:
            with _git_lock:
                self._notify("git_add_start", "Git: Adding file...")
                subprocess.run(
                    ["git", "add", str(file_path)],
                    cwd=self.repo_path, check=True, capture_output=True, text=True,
                )
                self._notify("git_commit_start", "Git: Committing...")
                subprocess.run(
                    ["git", "commit", "-m", message],
                    cwd=self.repo_path, check=True, capture_output=True, text=True,
                )
                self._notify("git_commit_success", "Git: Changes committed")

                if self.repo_push:
                    push_target = self.pr_branch or self.repo_branch or "main"
                    self._notify("git_push_start", f"Git: Pushing to {push_target}...")
                    subprocess.run(
                        ["git", "push", "-u", "origin", push_target],
                        cwd=self.repo_path, check=True, capture_output=True, text=True, timeout=30,
                    )
                    self._notify("git_push_success", f"Git: Pushed to {push_target}")
            return True
        except subprocess.TimeoutExpired:
            self._notify("git_error", "Git: Push timeout after 30s")
            return False
        except Exception as e:
            self._notify("git_error", f"Git: Commit failed - {str(e)[:100]}")
            return False

    def batch_commit_and_push(self, custom_message: str = None) -> bool:
        """Commit all staged files in one batch and push once."""
        if not self._pending_commits:
            self._notify("git_batch_skip", "Git: No files to batch commit")
            return True

        count = len(self._pending_commits)
        self._notify("git_batch_start", f"Git: Batch committing {count} file(s)...")

        if custom_message:
            message = custom_message
        else:
            categories = sorted(set(c["category"] for c in self._pending_commits if c["category"]))
            cat_summary = ", ".join(categories[:5])
            if len(categories) > 5:
                cat_summary += f" (+{len(categories) - 5} more)"

            file_list = "\n".join(f"  - {c['path'].name}" for c in self._pending_commits[:20])
            if count > 20:
                file_list += f"\n  ... and {count - 20} more"

            message = (
                f"Add {count} code example(s)\n\n"
                f"Categories: {cat_summary or 'uncategorized'}\n"
                f"Files:\n{file_list}"
            )

        try:
            with _git_lock:
                self._notify("git_commit_start", f"Git: Committing {count} file(s)...")
                subprocess.run(
                    ["git", "commit", "-m", message],
                    cwd=self.repo_path, check=True, capture_output=True, text=True,
                )
                self._notify("git_commit_success", f"Git: Batch committed {count} file(s)")

                if self.repo_push:
                    push_target = self.pr_branch or self.repo_branch or "main"
                    self._notify("git_push_start", f"Git: Pushing {count} file(s) to {push_target}...")
                    subprocess.run(
                        ["git", "push", "-u", "origin", push_target],
                        cwd=self.repo_path, check=True, capture_output=True, text=True, timeout=60,
                    )
                    self._notify("git_push_success", f"Git: Pushed {count} file(s) to {push_target}")

            self._pending_commits.clear()
            return True
        except subprocess.TimeoutExpired:
            self._notify("git_error", "Git: Batch push timeout after 60s")
            return False
        except Exception as e:
            self._notify("git_error", f"Git: Batch commit/push failed - {str(e)[:100]}")
            return False
