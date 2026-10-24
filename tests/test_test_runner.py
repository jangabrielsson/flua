"""flua test: the self-asserting test-QA runner (src/flua/test_cli.py)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_flua_test_runs_and_reports(tmp_path) -> None:
    (tmp_path / "ok_test.lua").write_text(
        '--%%name:ok_test\nlocal t = require("flua-test").new()\n'
        't:expect(true, "always")\nt:finish()\n'
    )
    (tmp_path / "bad_test.lua").write_text(
        '--%%name:bad_test\nlocal t = require("flua-test").new()\n'
        't:expect(false, "nope")\nt:finish()\n'
    )
    result = _run("test", cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PASS  ok_test.lua" in result.stdout
    assert "FAIL  bad_test.lua  (failures: 1)" in result.stdout
    assert "1 passed, 1 failed, 0 timed out" in result.stdout


def test_flua_test_timeout(tmp_path) -> None:
    # a test QA that never exits hits the per-file wall-clock timeout and
    # is reported separately — it must not block the rest of the run
    (tmp_path / "hang_test.lua").write_text(
        "--%%name:hang_test\nsetInterval(function() end, 1000)\n"
    )
    result = _run("test", "--timeout", "2", cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "TIME  hang_test.lua" in result.stdout
    assert "t:finish()/exit(...)" in result.stdout
    assert "0 passed, 0 failed, 1 timed out" in result.stdout


def test_flua_test_discovery_and_list(tmp_path) -> None:
    # discovery: *_test.lua files, hidden directories skipped; explicit
    # file arguments run regardless of their name
    (tmp_path / "found_test.lua").write_text(
        '--%%name:found_test\nlocal t = require("flua-test").new()\nt:finish()\n'
    )
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "skip_test.lua").write_text("print('nope')\n")
    (tmp_path / "plain.lua").write_text(
        "print('not a test')\nsetInterval(function() end, 1000)\n"
    )

    result = _run("test", "--list", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "found_test.lua" in result.stdout
    assert "skip_test.lua" not in result.stdout
    assert "plain.lua" not in result.stdout

    # an explicit file arg runs even without the *_test.lua name (it hangs,
    # so it times out — the point is that it was run at all)
    result = _run("test", "--timeout", "2", "plain.lua", cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "TIME  plain.lua" in result.stdout

    # no tests found is not an error
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _run("test", cwd=empty)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no *_test.lua files found" in result.stdout
