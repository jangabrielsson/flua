"""Render the HTML subset the HC3 console supports in QA log messages.

QAs on the real HC3 log with HTML tags — <b>, <i>, <u>, <font color="...">,
<span style="color:...">, <table>/<tr>/<td>/<th>, <ul>/<ol>/<li>, <br/> — and
the console renders them. flua renders the same subset to the terminal:
formatting becomes ANSI (when colors are on) and tables/lists become plain
text layout; with colors off, tags are stripped so the text stays readable.
Unknown tags are stripped, their content kept.
"""

from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_BOLD = "\x1b[1m"
_ITALIC = "\x1b[3m"
_UNDERLINE = "\x1b[4m"
_DEFAULT_FG = "\x1b[39m"

_NAMED_COLORS = {
    "black": 30,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "blue": 34,
    "magenta": 35,
    "cyan": 36,
    "white": 37,
}

# <name ...> opening/closing tags (the subset above plus the ones we strip)
_TAG_RE = re.compile(r"<(/)?\s*([a-zA-Z][a-zA-Z0-9]*)([^>]*)>", re.S)
_BR_RE = re.compile(r"<br\s*/?>", re.I)


def _color_code(spec: str) -> str | None:
    """``red`` or ``#rrggbb`` -> SGR color code; None when unknown."""
    spec = spec.strip().strip(";'\"").lower()
    if spec in _NAMED_COLORS:
        return f"\x1b[{_NAMED_COLORS[spec]}m"
    match = re.fullmatch(r"#?([0-9a-f]{6})", spec)
    if match:
        r, g, b = (int(match.group(1)[i : i + 2], 16) for i in (0, 2, 4))
        return f"\x1b[38;2;{r};{g};{b}m"
    return None


def _visible(text: str) -> int:
    """Visible length (ANSI escapes excluded) — for column padding."""
    return len(_ANSI.sub("", text))


def _inline(text: str, use_color: bool) -> str:
    """Formatting tags and <br/>; anything else loses its tags, keeps its
    content."""
    text = _BR_RE.sub("\n", text)
    if not use_color:
        return _TAG_RE.sub("", text)
    out: list[str] = []
    pos = 0
    color_stack: list[str] = []
    for match in _TAG_RE.finditer(text):
        out.append(text[pos : match.start()])
        pos = match.end()
        name = match.group(2).lower()
        closing = match.group(1) == "/"
        attrs = match.group(3)
        if name == "b" or name == "strong":
            out.append("\x1b[22m" if closing else _BOLD)
        elif name == "i" or name == "em":
            out.append("\x1b[23m" if closing else _ITALIC)
        elif name == "u":
            out.append("\x1b[24m" if closing else _UNDERLINE)
        elif (name == "font" or name == "span") and not closing:
            spec = re.search(r'color\s*[:=]\s*"([^"]*)"', attrs, re.I)
            if spec is None:
                spec = re.search(r"color\s*[:=]\s*'([^']*)'", attrs, re.I)
            if spec is None:
                spec = re.search(r"color\s*[:=]\s*(\S+)", attrs, re.I)
            code = _color_code(spec.group(1)) if spec else None
            if code:
                color_stack.append(code)
                out.append(code)
            else:
                out.append("")  # <font>/<span> without a known color: drop it
        elif (name == "font" or name == "span") and closing:
            if color_stack:
                color_stack.pop()
                out.append(_DEFAULT_FG)
            else:
                out.append("")
        else:
            out.append("")  # unknown tag: stripped
    out.append(text[pos:])
    return "".join(out)


def _table(html: str, use_color: bool) -> str:
    rows: list[list[str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.I | re.S)
        if cells:
            rows.append([_inline(cell.strip(), use_color) for cell in cells])
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    widths = [
        max((_visible(row[i]) for row in rows if i < len(row)), default=0)
        for i in range(width)
    ]
    lines = []
    for row in rows:
        padded = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        lines.append(padded.rstrip())
    return "\n" + "\n".join(lines) + "\n"


def _list(html: str, use_color: bool) -> str:
    ordered = html.lstrip().lower().startswith("<ol")
    items = re.findall(r"<li[^>]*>(.*?)</li>", html, re.I | re.S)
    lines = []
    for index, item in enumerate(items):
        prefix = f"{index + 1}. " if ordered else "- "
        lines.append(prefix + _inline(item.strip(), use_color))
    return ("\n" + "\n".join(lines) + "\n") if lines else ""


_TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.I | re.S)
_LIST_RE = re.compile(r"<(ul|ol)[^>]*>.*?</\1>", re.I | re.S)


def render_html(text: str, use_color: bool) -> str:
    """Render one log message: blocks first (tables, lists), then inline
    formatting; anything unrecognized is reduced to plain text."""
    text = _TABLE_RE.sub(lambda m: _table(m.group(0), use_color), text)
    text = _LIST_RE.sub(lambda m: _list(m.group(0), use_color), text)
    return _inline(text, use_color)
