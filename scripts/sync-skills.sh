#!/usr/bin/env bash
# Sync .github/skills -> the packaged copies that ship in the wheel, and
# the docs -> the copies the flua-mcp resource tier serves from pip
# installs.
#
# The repo trees are the source of truth; the packaged trees
# (src/flua/setup_templates/...) are what --tool setup installs, what
# --tool newQA reads, and what flua-mcp serves. tests/test_tools.py's sync
# guard fails when the two drift — this script is the manual way back in
# sync:
#
#   edit .github/skills/... (or any doc) && ./scripts/sync-skills.sh
#
# SKILLS_SRC/SKILLS_DEST and DOCS_SRC/DOCS_DEST override the paths (the
# sync test runs against temp copies so a test run never rewrites the repo
# tree).
set -euo pipefail

cd "$(dirname "$0")/.."

SRC_DIR="${SKILLS_SRC:-.github/skills}"
DEST="${SKILLS_DEST:-src/flua/setup_templates/github/skills}"

rm -rf "$DEST"
cp -R "$SRC_DIR" "$DEST"
echo "synced $SRC_DIR -> $DEST"

DOCS_SRC="${DOCS_SRC:-docs}"
DOCS_DEST="${DOCS_DEST:-src/flua/setup_templates/docs}"

rm -rf "$DOCS_DEST"
mkdir -p "$DOCS_DEST"
# Root-only docs ship alongside the tree; root README.md is skipped on
# purpose — docs/README.md (the documentation index) owns that name, so
# flua://docs/README.md is unambiguous.
cp USAGE.md ARCHITECTURE.md CONTRIBUTING.md "$DOCS_DEST/"
cp -R "$DOCS_SRC/." "$DOCS_DEST/"
echo "synced docs -> $DOCS_DEST"
