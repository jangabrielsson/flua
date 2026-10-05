#!/usr/bin/env bash
# Build the single-PDF edition of the tutorial (docs/tutorial/*.md) with a
# table of contents. Pandoc assembles the chapters into one HTML page
# (mermaid diagrams included), then headless Chrome prints it to PDF — the
# only route that renders the mermaid diagrams as pictures.
#
# Requirements: pandoc, Google Chrome (macOS path below). The mermaid
# library is fetched from jsdelivr at build time; without network the
# diagrams appear as their source text.
#
# Usage:
#   ./scripts/build-tutorial-pdf.sh          # -> docs/tutorial/flua-tutorial.pdf
#   PDF=/tmp/tutorial.pdf ./scripts/build-tutorial-pdf.sh
set -euo pipefail

cd "$(dirname "$0")/.."

OUT="${PDF:-docs/tutorial/flua-tutorial.pdf}"
HTML="$(mktemp -t flua-tutorial).html"

pandoc \
  --standalone \
  --toc --toc-depth=2 \
  --metadata title="flua — QuickApps for the rest of us" \
  --template docs/tutorial/pdf-template.html \
  --lua-filter docs/tutorial/mermaid-filter.lua \
  docs/tutorial/README.md docs/tutorial/0*.md \
  -o "$HTML"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME" ]]; then
  echo "Google Chrome not found at $CHROME — install it or set CHROME=/path/to/chrome" >&2
  exit 1
fi

# --virtual-time-budget lets mermaid finish rendering before the print
# (Chrome's headless stderr on macOS is harmless noise — dropped)
"$CHROME" --headless=new --disable-gpu --no-sandbox \
  --no-pdf-header-footer \
  --virtual-time-budget=15000 \
  --print-to-pdf="$OUT" "file://$HTML" 2>/dev/null

rm -f "$HTML"
echo "wrote $OUT"
