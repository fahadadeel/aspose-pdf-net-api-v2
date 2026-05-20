#!/usr/bin/env bash
# REVERT.sh — undo the Flow A / Flow B "human-attributed merge" implementation.
#
# What this does:
#   1. Restores the 5 tracked files I modified back to their last committed state
#      via `git restore` (safe — only touches files listed below).
#   2. Deletes the 3 new files I created in scripts/.
#   3. Restores .claude/rules/env-vars.md from the backed-up original (this file
#      is untracked so `git restore` can't help it).
#   4. Leaves .env alone (your personal secrets).
#   5. Leaves .backups/ alone.
#
# Run from any directory — the script cd's to the repo root itself.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "Repo root: $REPO_ROOT"
echo

TRACKED=(
  "config.py"
  "git_ops/github_api.py"
  "jobs.py"
  "scripts/parallel_run.py"
  "scripts/README.md"
)

NEW_FILES=(
  "scripts/merge_release_prs.py"
  "scripts/rollback.py"
  "scripts/rollback_snapshot.py"
)

echo "Restoring tracked files to HEAD..."
for f in "${TRACKED[@]}"; do
  if [[ -f "$f" ]]; then
    git restore -- "$f"
    echo "  restored: $f"
  else
    echo "  skipped (missing): $f"
  fi
done

echo
echo "Removing new files..."
for f in "${NEW_FILES[@]}"; do
  if [[ -f "$f" ]]; then
    rm -- "$f"
    echo "  removed: $f"
  else
    echo "  skipped (missing): $f"
  fi
done

echo
echo "Restoring untracked doc file..."
if [[ -f "$SCRIPT_DIR/.claude/rules/env-vars.md.original" ]]; then
  cp "$SCRIPT_DIR/.claude/rules/env-vars.md.original" ".claude/rules/env-vars.md"
  echo "  restored: .claude/rules/env-vars.md"
else
  echo "  WARNING: backup of env-vars.md.original is missing"
fi

echo
echo "Done. Current git status:"
git status --short
echo
echo "Note: .env is untouched. If you added MERGE_ACCT_GITHUB_TOKEN / BOT_GITHUB_LOGIN"
echo "and want them gone, remove those lines manually."
