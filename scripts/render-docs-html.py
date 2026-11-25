#!/usr/bin/env python3
"""Render the core .md reference docs into themed .html pages.

The forum posts are authored HTML; the longer reference docs (USAGE,
ARCHITECTURE, concurrency, walkthroughs, invariants) are markdown, which
the /docs channel used to serve as plain text — raw, unreadable in a
browser. This script renders the docs listed in PAGES into sibling .html
pages with the docs theme (VS Code webview variables with browser
fallbacks). The rendered pages are committed, so a pip-installed flua
serves them with zero runtime markdown dependency — ``markdown`` is a
dev-only extra.

The GitHub-flavored subset the docs use: tables, fenced code blocks, sane
lists. Raw HTML in the sources passes through untouched.

Run without arguments to (re)write docs/**/*.html (scripts/sync-skills.sh
does this before copying the docs into the package); run with --check to
render into a temp tree and exit 1 when the committed pages have drifted —
tests/test_tools.py's sync guard calls it that way, so a doc edit that
forgets to re-render fails the suite instead of shipping stale HTML.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# (markdown source, rendered page) — the root-level guides render into the
# docs tree so scripts/sync-skills.sh copies them into the package with
# everything else; the /docs landing page (gen-forum-index.py) links them.
# Adding a page here adds its .html — point the landing page at it and
# commit both.
PAGES = [
    (ROOT / "USAGE.md", DOCS / "USAGE.html"),
    (ROOT / "ARCHITECTURE.md", DOCS / "ARCHITECTURE.html"),
    (DOCS / "concurrency.md", DOCS / "concurrency.html"),
    (DOCS / "walkthroughs.md", DOCS / "walkthroughs.html"),
    (DOCS / "invariants.md", DOCS / "invariants.html"),
]

# the docs theme: VS Code webviews have no browser defaults, so the pages
# read the theme's CSS variables, with the ordinary browser palette as
# fallbacks (same approach as the forum landing page).
_STYLE = """
  body { font-family: var(--vscode-font-family, -apple-system, "Segoe UI", system-ui, sans-serif);
         max-width: 52rem; margin: 2rem auto; padding: 0 1rem;
         background: var(--vscode-editor-background, #fff);
         color: var(--vscode-editor-foreground, #1c2b3a);
         line-height: 1.55; }
  h1, h2, h3, h4 { color: var(--vscode-textLink-foreground, #003a70); font-weight: 600; }
  h2 { border-bottom: 1px solid var(--vscode-panel-border, #dce6ee);
       padding-bottom: .3rem; margin-top: 2rem; }
  code { font-family: var(--vscode-editor-font-family, ui-monospace,
               SFMono-Regular, Menlo, monospace);
         background: var(--vscode-textCodeBlock-background, #f2f4f6);
         padding: .15em .35em; border-radius: 4px; font-size: 90%; }
  pre { background: var(--vscode-textCodeBlock-background, #f2f4f6);
        padding: .8rem 1rem; border-radius: 6px; overflow-x: auto; }
  pre code { background: none; padding: 0; }
  table { border-collapse: collapse; margin: 1rem 0; max-width: 100%; }
  th, td { border: 1px solid var(--vscode-panel-border, #dce6ee);
           padding: .35rem .6rem; text-align: left; vertical-align: top; }
  th { background: var(--vscode-textCodeBlock-background, #f2f4f6); }
  a { color: var(--vscode-textLink-foreground, #0a6cff); text-decoration: none; }
  blockquote { border-left: 3px solid var(--vscode-panel-border, #dce6ee);
               margin: 1rem 0; padding: .1rem 1rem;
               color: var(--vscode-descriptionForeground, #5b6b7a); }
  img { max-width: 100%; }
"""


def _title(text: str, name: str) -> str:
    """The page title: the first level-1 heading, else the file name."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return name


def render(text: str, title: str) -> str:
    """The full .html page for one markdown source."""
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    return (
        "<!doctype html>\n"
        '<html>\n<head>\n<meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        f"<style>{_STYLE}</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )


def _render_page(src: Path) -> str:
    text = src.read_text(encoding="utf-8")
    return render(text, _title(text, src.name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="render into a temp tree and exit 1 when the committed .html "
        "pages have drifted (rerun without --check to fix)",
    )
    args = parser.parse_args(argv)

    if not args.check:
        for src, dst in PAGES:
            if not src.is_file():
                parser.error(f"missing doc source: {src}")
            html = _render_page(src)
            dst.write_text(html, encoding="utf-8")
            print(f"rendered {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
        return 0

    drifted: list[str] = []
    for src, dst in PAGES:
        html = _render_page(src).encode("utf-8")
        try:
            if dst.read_bytes() != html:
                drifted.append(str(dst.relative_to(ROOT)))
        except FileNotFoundError:
            drifted.append(f"{dst.relative_to(ROOT)} (missing)")
    if drifted:
        print(
            "rendered docs drifted — run scripts/render-docs-html.py: "
            + ", ".join(drifted),
            file=sys.stderr,
        )
        return 1
    print("rendered docs up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
