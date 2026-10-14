#!/usr/bin/env bash
# Sync .github/skills -> the packaged copies that ship in the wheel.
#
# The repo tree (.github/skills) is the source of truth; the packaged tree
# (src/flua/setup_templates/github/skills) is what --tool setup installs and
# what --tool newQA reads. tests/test_tools.py's sync guard fails when the
# two drift — this script is the manual way back in sync:
#
#   edit .github/skills/... && ./scripts/sync-skills.sh
#
# SKILLS_SRC/SKILLS_DEST override the paths (the sync test runs against
# temp copies so a test run never rewrites the repo tree).
set -euo pipefail

cd "$(dirname "$0")/.."

SRC_DIR="${SKILLS_SRC:-.github/skills}"
DEST="${SKILLS_DEST:-src/flua/setup_templates/github/skills}"

rm -rf "$DEST"
cp -R "$SRC_DIR" "$DEST"
echo "synced $SRC_DIR -> $DEST"
