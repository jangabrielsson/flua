#!/usr/bin/env bash
# Release flua: bump the version, tag, push, and publish a GitHub Release.
# Publishing the release fires .github/workflows/publish-to-pypi.yml, which
# builds and uploads to PyPI using the PYPI_API_TOKEN repository secret.
#
# Usage:
#   ./scripts/release.sh            # bump the patch version (0.1.0 -> 0.1.1)
#   ./scripts/release.sh minor      # bump minor (0.1.0 -> 0.2.0)
#   ./scripts/release.sh major      # bump major (0.1.0 -> 1.0.0)
#   ./scripts/release.sh 0.5.0      # set an exact version
#
# Requirements:
#   - a clean git tree
#   - the test suite passing
#   - 'gh' installed and authenticated (gh auth login)
#   - a PYPI_API_TOKEN repository secret (GitHub -> Settings -> Secrets and
#     variables -> Actions) holding a PyPI API token for the fibaro-flua
#     project (the same kind of token you keep in ~/.pypirc)
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION_FILE=src/flua/__init__.py
CURRENT=$(grep -o '__version__ = "[^"]*"' "$VERSION_FILE" | grep -o '"[^"]*"' | tr -d '"')

if [ -z "$CURRENT" ]; then
  echo "could not read the current version from $VERSION_FILE" >&2
  exit 1
fi

if [ $# -eq 1 ] && [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  NEW="$1"
else
  LEVEL="${1:-patch}"
  IFS=. read -r major minor patch <<< "$CURRENT"
  case "$LEVEL" in
    major) NEW="$((major + 1)).0.0" ;;
    minor) NEW="$major.$((minor + 1)).0" ;;
    patch) NEW="$major.$minor.$((patch + 1))" ;;
    *) echo "unknown bump level: $LEVEL (expected major|minor|patch or X.Y.Z)" >&2; exit 1 ;;
  esac
fi

if [ "$NEW" = "$CURRENT" ]; then
  echo "already at version $CURRENT" >&2
  exit 1
fi

echo "releasing $CURRENT -> $NEW"

# 1. clean tree
if [ -n "$(git status --porcelain)" ]; then
  echo "working tree is not clean; commit or stash first" >&2
  exit 1
fi

# 2. tests
echo "running tests..."
.venv/bin/python -m pytest -q

# 3. bump (macOS/BSD sed needs the -i.bak form; GNU sed accepts it too)
sed -i.bak "s/__version__ = \"$CURRENT\"/__version__ = \"$NEW\"/" "$VERSION_FILE"
rm -f "$VERSION_FILE.bak"
sed -i.bak "s/^version = \"$CURRENT\"/version = \"$NEW\"/" pyproject.toml
rm -f pyproject.toml.bak
grep "__version__" "$VERSION_FILE"
grep "^version" pyproject.toml

# 4. changelog: generate the [NEW] section from the commits since v$CURRENT
#    (conventional-commit subjects, grouped Added/Changed/Fixed). Runs before
#    the bump commit, so the bump commit itself is not listed.
python3 - "$CURRENT" "$NEW" <<'PYEOF'
import re
import subprocess
import sys
from datetime import date

current, new = sys.argv[1], sys.argv[2]
log = subprocess.run(
    ["git", "log", "--pretty=format:%s", f"v{current}..HEAD"],
    capture_output=True,
    text=True,
)
if log.returncode != 0:
    sys.exit(
        f"no commits since tag v{current} (is it tagged?) — "
        f"tag the base first or pass the exact base version"
    )
subjects = [line for line in log.stdout.splitlines() if line.strip()]
groups = {"Added": [], "Changed": [], "Fixed": []}
for subject in subjects:
    match = re.match(r"^(feat|fix|refactor|docs|chore|perf)(\([^)]*\))?:\s*(.*)$", subject)
    kind, text = (match.group(1), match.group(3)) if match else ("", subject)
    bucket = "Added" if kind == "feat" else "Fixed" if kind == "fix" else "Changed"
    groups[bucket].append(text)
if not any(groups.values()):
    groups["Changed"].append("Housekeeping")
lines = [f"## [{new}] - {date.today().isoformat()}", ""]
for bucket, entries in groups.items():
    if entries:
        lines.append(f"### {bucket}")
        for entry in entries:
            lines.append(f"- {entry}")
        lines.append("")
path = "CHANGELOG.md"
with open(path, encoding="utf-8") as handle:
    doc = handle.read()
marker = "## ["
index = doc.find(marker)
if index < 0:
    sys.exit(f"{path}: no version sections found")
doc = doc[:index] + "\n".join(lines) + "\n" + doc[index:]
with open(path, "w", encoding="utf-8") as handle:
    handle.write(doc)
print(f"wrote {path} section for {new}")
PYEOF

# 5. commit + tag
git add pyproject.toml "$VERSION_FILE" CHANGELOG.md
git commit -m "chore: release $NEW"
git tag "v$NEW"

# 6. push — the tag alone triggers nothing; the RELEASE does
git push origin HEAD
git push origin "v$NEW"

# 7. publish the GitHub Release -> fires the PyPI workflow
if command -v gh >/dev/null 2>&1; then
  gh release create "v$NEW" --generate-notes --title "flua $NEW"
  echo "release published — the PyPI workflow is running."
  echo "watch it with:  gh run watch"
else
  echo "gh not found. Create the release manually to fire the workflow:"
  echo "  https://github.com/<owner>/flua/releases/new?tag=v$NEW"
fi
