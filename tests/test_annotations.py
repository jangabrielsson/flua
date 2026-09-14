"""CLI-level tests for --%% config annotations."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("lupa")

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_flua(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_instant_annotation_runs_hour_timer_instantly(tmp_path) -> None:
    script = tmp_path / "instant.lua"
    script.write_text(
        "--%%instant:true\n"
        "local t0 = os.time()\n"
        "setTimeout(function() print('DT', os.time() - t0); exit(0) end, 3600000)\n"
    )
    result = _run_flua(str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DT 3600" in result.stdout


def test_time_annotation_with_subparams(tmp_path) -> None:
    script = tmp_path / "time.lua"
    script.write_text(
        "--%%time:instant=true,speed=2\n"
        "local t0 = os.time()\n"
        "setTimeout(function() print('DT', os.time() - t0); exit(0) end, 3600000)\n"
    )
    result = _run_flua(str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DT 3600" in result.stdout


def test_cli_flag_overrides_annotation(tmp_path) -> None:
    script = tmp_path / "override.lua"
    script.write_text(
        "--%%instant:true\n"
        "local t0 = _FLUA.millitime()\n"
        "setTimeout(function()\n"
        "  print('DT', _FLUA.millitime() - t0)\n"
        "  exit(0)\n"
        "end, 200)\n"
    )
    # CLI --speed 2 wins: accelerated (0.2 virtual s), NOT instant
    result = _run_flua("--speed", "2", str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"DT (\d+)", result.stdout)
    assert match, result.stdout
    dt = float(match.group(1))
    assert 150 < dt < 250  # 200 virtual ms, accelerated (not instant)


def test_maxhours_annotation_stops_endless_interval(tmp_path) -> None:
    script = tmp_path / "cap.lua"
    script.write_text(
        "--%%time:instant=true,hours=1\n"
        "setInterval(function() print('tick') end, 60000)\n"  # forever
    )
    result = _run_flua(str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "virtual time limit reached (1h)" in result.stderr


def test_config_exposed_to_lua(tmp_path) -> None:
    script = tmp_path / "cfg.lua"
    script.write_text(
        "--%%speed:7\n"        # global param: copied up to the global config
        "--%%myparam:hello\n"  # local param: visible on the QA's config
        "print('CFG', _FLUA.config.speed, _FLUA.config.myparam)\n"
        "exit(0)\n"
    )
    result = _run_flua(str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CFG 7 hello" in result.stdout