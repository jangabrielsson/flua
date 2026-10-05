#!/usr/bin/env bash
# Contribution workflow: gate -> branch -> commit -> push -> pull request.
#
# Usage:
#   git add <files you want in the PR>          # stage ONLY what belongs in it
#   ./scripts/pr.sh my-fix "feat: describe the change"
#
# The script runs the project's gate (ruff + the full offline suite) on the
# working tree, then creates contrib/<slug>, commits the STAGED changes with
# your message, pushes, and opens the PR with gh (--fill: the body comes from
# the commits). The branch/commit/test steps work for everyone; opening the
# PR needs 'gh' and push access (fork contributors run `gh pr create --fill`
# from their fork instead — the script prints the manual path if gh is
# missing).
#
# Nothing is pushed unless the gate passes. Unstaged changes stay unstaged —
# they are never swept into the PR.
set -euo pipefail

cd "$(dirname "$0")/.."

SLUG="${1:?usage: ./scripts/pr.sh <branch-slug> <commit-message>}"
MESSAGE="${2:?usage: ./scripts/pr.sh <branch-slug> <commit-message>}"
BRANCH="contrib/$SLUG"

if git diff --cached --quiet; then
  echo "nothing staged — git add the files for the PR first" >&2
  exit 1
fi

# the gate — the same commands the contribution rules demand
.venv/bin/ruff check src/ tests/
.venv/bin/pytest tests/ -q --ignore=tests/test_hc3_live.py --ignore=tests/test_hc3_compat.py

git checkout -b "$BRANCH" 2>/dev/null || git checkout "$BRANCH"
git commit -m "$MESSAGE"
git push -u origin "$BRANCH"

if command -v gh >/dev/null 2>&1; then
  gh pr create --fill
  echo "PR opened — watch the tests run in the Actions tab."
else
  echo "gh not found. Open the PR manually (the branch is pushed):"
  echo "  https://github.com/jangabrielsson/flua/compare/main...$BRANCH"
fi
