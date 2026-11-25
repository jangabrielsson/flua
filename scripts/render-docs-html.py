#!/usr/bin/env python3
"""Render the markdown docs into themed .html pages for the /docs channel.

The forum posts are authored HTML; the reference docs (USAGE,
ARCHITECTURE, concurrency, ...) are markdown, which the /docs channel used
to serve as plain text — raw, unreadable in a browser. This script renders
every .md in docs/ (plus the root-level USAGE/ARCHITECTURE/CONTRIBUTING,
which the served tree flattens to the same level) into a sibling .html
with the docs theme (VS Code webview variables with browser fallbacks).
The rendered pages are committed, so a pip-installed flua serves them with
zero runtime markdown dependency — ``markdown`` is a dev-only extra.

Rendering details:

- headings get GitHub-style anchor ids (``#qa-directives---``), so the
  tables of contents in the sources keep working;
- relative links are rewritten to the served tree: the repo-root paths
  ``docs/x.md`` and ``../x.md`` both become ``x.html``, so cross-doc links
  resolve under /docs/;
- tables, fenced code blocks and sane lists (the GFM subset the docs use).

Run without arguments to (re)write the pages (scripts/sync-skills.sh does
this before copying the docs into the package); run with --check to render
in memory and exit 1 when the committed pages have drifted —
tests/test_tools.py's sync guard calls it that way, so a doc edit that
forgets to re-render fails the suite instead of shipping stale HTML.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# the root-level guides (the served tree flattens them into the docs root)
_ROOT_PAGES = ["USAGE.md", "ARCHITECTURE.md", "CONTRIBUTING.md"]

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


def _github_slugify(value: str) -> str:
    """GitHub's heading-anchor slug: lowercase, keep alphanumerics, ``-``
    and ``_``, drop everything else, each surviving space becomes a dash
    (consecutive dashes survive — ``QA directives (`--%%`)`` is
    ``qa-directives---``, ``flua — user guide`` is ``flua--user-guide``).
    The docs' tables of contents use these anchors."""
    kept = "".join(ch if ch.isalnum() or ch in "-_ " else "" for ch in value.lower())
    return kept.replace(" ", "-").replace("\t", "-")


def _rewrite_href(href: str) -> str:
    """A relative link target, rewritten for the served /docs tree: the
    repo-root prefixes ``docs/`` and ``../`` flatten away, and .md targets
    point at their rendered .html (``docs/concurrency.md`` ->
    ``concurrency.html``). Absolute URLs and pure #anchors pass through.
    """
    if not href or href.startswith(("#", "http://", "https://", "mailto:")):
        return href
    path_part, sep, fragment = href.partition("#")
    while path_part.startswith("../"):
        path_part = path_part[3:]
    if path_part.startswith("docs/"):
        path_part = path_part[len("docs/") :]
    if path_part.endswith(".md"):
        path_part = path_part[:-3] + ".html"
    return path_part + (sep + fragment if sep else "")


_HREF = re.compile(r'href="([^"]*)"')

# heading injection: each <hN> gets its GitHub-style anchor id, computed
# from the VISIBLE heading text (markup stripped, entities unescaped) — the
# toc extension's own slugify pre-normalizes whitespace and breaks em-dash
# headings, so ids are computed here instead
_HEADING = re.compile(r"<h([1-6])([^>]*)>(.*?)</h\1>", re.S)
_TAG = re.compile(r"<[^>]+>")


def _inject_heading_ids(body: str) -> str:
    used: dict[str, int] = {}

    def sub(m: re.Match[str]) -> str:
        level, attrs, content = m.group(1), m.group(2), m.group(3)
        visible = html.unescape(_TAG.sub("", content))
        slug = _github_slugify(visible)
        if slug in used:  # duplicate headings: GitHub's -1, -2 suffixes
            used[slug] += 1
            slug = f"{slug}-{used[slug]}"
        else:
            used[slug] = 0
        return f'<h{level}{attrs} id="{slug}">{content}</h{level}>'

    return _HEADING.sub(sub, body)


def _pages() -> list[tuple[Path, Path]]:
    """Every (markdown source, rendered page): the root-level guides
    render into docs/ (the served tree flattens them there), every doc in
    the docs tree gets a sibling .html."""
    pairs = [(ROOT / name, DOCS / (name[:-3] + ".html")) for name in _ROOT_PAGES]
    pairs += [
        (md, md.with_suffix(".html"))
        for md in sorted(DOCS.rglob("*.md"))
        if md.stem.lower() != "index"
        # INDEX.md is a page SOURCE (the forum landing page's), not a page:
        # its rendered INDEX.html would collide with the generated index.html
        # on case-insensitive filesystems
    ]
    return pairs


def _title(text: str, name: str) -> str:
    """The page title: the first level-1 heading, else the file name."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return name


def render(text: str, title: str) -> str:
    """The full .html page for one markdown source."""
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
    body = md.convert(text)
    body = _inject_heading_ids(body)
    body = _HREF.sub(lambda m: f'href="{_rewrite_href(m.group(1))}"', body)
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
        help="render in memory and exit 1 when the committed .html pages "
        "have drifted (rerun without --check to fix)",
    )
    args = parser.parse_args(argv)

    if not args.check:
        pages = _pages()
        for src, dst in pages:
            if not src.is_file():
                parser.error(f"missing doc source: {src}")
            dst.write_text(_render_page(src), encoding="utf-8")
        print(f"rendered {len(pages)} markdown docs")
        return 0

    drifted: list[str] = []
    for src, dst in _pages():
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
