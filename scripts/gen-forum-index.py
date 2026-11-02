#!/usr/bin/env python3
"""Generate docs/forum/index.html — the web docs landing page.

Titles come from each post's <h2>; the "covers" summaries come from
INDEX.md's table. Run by scripts/sync-skills.sh so the packaged docs tree
stays in sync; regenerating is idempotent.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FORUM = Path(__file__).resolve().parent.parent / "docs" / "forum"


def html_title(path: Path) -> str:
    match = re.search(r"<h2>(.*?)</h2>", path.read_text(encoding="utf-8"), re.S)
    if match is None:
        return path.stem
    return re.sub(r"<[^>]+>", "", match.group(1)).strip()


def covers() -> dict[str, str]:
    """file name -> the covers column from INDEX.md's table."""
    index = (FORUM / "INDEX.md").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for line in index.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 5 and cells[1].endswith(".html"):
            out[cells[1]] = cells[3]
    return out


def main() -> int:
    summaries = covers()
    posts = sorted(
        (p for p in FORUM.glob("*.html") if p.name != "index.html"),
        key=lambda p: (p.name[:2].isdigit(), p.name),
    )
    series = [p for p in posts if re.match(r"^\d\d-", p.name)]
    standalone = [p for p in posts if not re.match(r"^\d\d-", p.name)]

    def entry(path: Path) -> str:
        title = html_title(path)
        summary = summaries.get(path.name, "")
        # channel-root links: the index is served at /docs/ (from forum/
        # index.html), so relative hrefs would resolve to /docs/<file> and
        # miss the forum/ subdirectory
        link = f'<a href="/docs/forum/{path.name}">{title}</a>'
        covers = f' <span class="covers">— {summary}</span>' if summary else ""
        return f"<li>{link}{covers}</li>"

    series_items = "\n".join(entry(p) for p in series)
    standalone_items = "\n".join(entry(p) for p in standalone)
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>flua docs</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
         max-width: 52rem; margin: 2rem auto; padding: 0 1rem; color: #1c2b3a; }}
  h1 {{ color: #003a70; }}
  h2 {{ border-bottom: 1px solid #dce6ee; padding-bottom: .3rem; margin-top: 2rem; }}
  a {{ color: #0a6cff; text-decoration: none; }}
  li {{ margin: .35rem 0; line-height: 1.4; }}
  .covers {{ color: #5b6b7a; }}
  ul.refs {{ columns: 2; }}
</style>
</head>
<body>
<h1>flua documentation</h1>
<p>Shipped with flua — this page and everything below it come from the
installed package, so the docs always match your version.</p>
<h2>Guides</h2>
<ul class="refs">
  <li><a href="/docs/USAGE.md">USAGE.md</a>
      <span class="covers">— the user guide (plain text)</span></li>
  <li><a href="/docs/ARCHITECTURE.md">ARCHITECTURE.md</a>
      <span class="covers">— internals</span></li>
  <li><a href="/docs/concurrency.md">concurrency.md</a>
      <span class="covers">— threading &amp; execution model</span></li>
  <li><a href="/docs/walkthroughs.md">walkthroughs.md</a>
      <span class="covers">— guided traces</span></li>
  <li><a href="/docs/invariants.md">invariants.md</a>
      <span class="covers">— behavioral contracts</span></li>
</ul>
<h2>The tutorial series</h2>
<ol>
{series_items}
</ol>
<h2>Standalone posts</h2>
<ul>
{standalone_items}
</ul>
</body>
</html>
"""
    (FORUM / "index.html").write_text(page, encoding="utf-8")
    print(f"wrote {FORUM / 'index.html'} ({len(series)} posts, {len(standalone)} standalone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
