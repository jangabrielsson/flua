"""Run tests/lua/*.lua end-to-end through the flua CLI.

Each script uses tests/lua/helpers.lua and must end with t.done(), which exits
0 on success and 1 on failure. Scripts are run without extra arguments, except
the arg-table round-trip case which is exercised explicitly.
"""

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("lupa")

REPO_ROOT = Path(__file__).resolve().parent.parent
LUA_TESTS = REPO_ROOT / "tests" / "lua"

ARGS_SCRIPT = "arg_roundtrip.lua"
EXCLUDED = {"helpers.lua", ARGS_SCRIPT}


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _assert_passed(result: subprocess.CompletedProcess[str], script_name: str) -> None:
    assert result.returncode == 0, (
        f"{script_name} exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "all passed" in result.stdout, (
        f"{script_name} never reached t.done()\nstdout:\n{result.stdout}"
    )


SCRIPTS = sorted(
    path for path in LUA_TESTS.glob("*.lua") if path.name not in EXCLUDED
)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
def test_lua_script(script: Path) -> None:
    _assert_passed(_run(script), script.name)


def test_arg_table_roundtrip() -> None:
    _assert_passed(_run(LUA_TESTS / ARGS_SCRIPT), ARGS_SCRIPT)
