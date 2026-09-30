"""The HC3 console's HTML log subset rendered to the terminal."""

import subprocess
import sys
from pathlib import Path

from flua.loghtml import render_html

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_formatting_tags_become_ansi() -> None:
    out = render_html("<b>bold</b> and <strong>strong</strong>", True)
    assert "\x1b[1mbold\x1b[22m" in out
    assert "and \x1b[1mstrong\x1b[22m" in out
    assert "<b>" not in out
    out = render_html("<i>it</i> <u>un</u>", True)
    assert "\x1b[3mit\x1b[23m" in out and "\x1b[4mun\x1b[24m" in out


def test_formatting_tags_stripped_without_color() -> None:
    out = render_html("<b>bold</b> <i>it</i> <br/> next", False)
    assert out == "bold it \n next"
    assert "\x1b" not in out


def test_font_colors() -> None:
    out = render_html('<font color="red">alert</font>', True)
    assert "\x1b[31malert\x1b[39m" in out
    out = render_html('<span style="color:#ff0000">hex</span>', True)
    assert "\x1b[38;2;255;0;0mhex\x1b[39m" in out
    # unknown colors drop the tag only (no dangling reset)
    out = render_html('<font color="chartreuse">x</font>', True)
    assert out == "x"


def test_table_renders_with_padded_columns() -> None:
    out = render_html(
        "<table><tr><th>Name</th><th>Value</th></tr>"
        "<tr><td>temp</td><td>21</td></tr></table>",
        True,
    )
    assert "\nName  Value\n" in out
    assert "\ntemp  21\n" in out
    assert "<table>" not in out


def test_lists() -> None:
    out = render_html("<ul><li>a</li><li>b</li></ul>", True)
    assert "\n- a\n- b\n" in out
    out = render_html("<ol><li>a</li><li>b</li></ol>", True)
    assert "\n1. a\n2. b\n" in out


def test_unknown_tags_stripped_content_kept() -> None:
    out = render_html("<blink>hi</blink> plain", True)
    assert out == "hi plain"


def test_console_renders_and_color_never_strips(tmp_path) -> None:
    script = tmp_path / "h.lua"
    script.write_text(
        'print("<b>bold</b>", '
        '"<table><tr><td>a</td><td>bb</td></tr><tr><td>ccc</td><td>d</td></tr></table>")\n'
        "exit(0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "\x1b[1mbold\x1b[22m" in result.stdout  # colors on by default
    assert "a    bb" in result.stdout  # padded table columns
    assert "ccc  d" in result.stdout
    assert "<b>" not in result.stdout

    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "--color", "never", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "\x1b" not in result.stdout  # no ANSI at all
    assert "<b>" not in result.stdout  # tags stripped
