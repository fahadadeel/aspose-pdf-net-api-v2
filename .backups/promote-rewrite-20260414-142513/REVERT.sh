#!/usr/bin/env bash
# Reverts the promote-to-main rewrite (force-update ref + tag_exists guard).
set -euo pipefail
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

git restore -- config.py git_ops/github_api.py jobs.py
echo "Reverted config.py, git_ops/github_api.py, jobs.py to HEAD."
git status --short
