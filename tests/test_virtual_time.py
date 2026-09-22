"""Engine-level tests for virtual time modes (instant / accelerated)."""

import math
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(*args: str, timeout: int = 30) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        [sys.executable, "-m", "flua", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def wait_until(predicate, timeout: float = 3.0) -> None:
    import asyncio

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_instant_mode_advances_virtual_time(capsys) -> None:
    engine = LuaEngine(speed=math.inf)
    await engine.start()
    try:
        engine.execute(
            "local t0 = os.time()\n"
            "setTimeout(function()\n"
            "  print('DT', os.time() - t0)\n"
            "  _FLUA.exit(0)\n"
            "end, 3600000)"  # one simulated hour
        )
        start = time.monotonic()
        await wait_until(lambda: not engine.is_running())
        assert time.monotonic() - start < 2.0  # "instant"
        assert "DT\t3600" in capsys.readouterr().out  # os.time() is integer seconds
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_instant_mode_preserves_deadline_order(capsys) -> None:
    engine = LuaEngine(speed=math.inf)
    await engine.start()
    try:
        engine.execute(
            "setTimeout(function() print('B') end, 2000)\n"
            "setTimeout(function() print('A') end, 1000)\n"
            "setTimeout(function() print('done'); _FLUA.exit(0) end, 3000)"
        )
        await wait_until(lambda: not engine.is_running())
        out = capsys.readouterr().out
        assert out.index("A") < out.index("B") < out.index("done")
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_accelerated_mode_fires_early_but_keeps_virtual_time(capsys) -> None:
    engine = LuaEngine(speed=10.0)
    await engine.start()
    try:
        start = time.monotonic()
        engine.execute(
            "local t0 = _FLUA.millitime()\n"
            "setTimeout(function()\n"
            "  print('FAST')\n"
            "  print('DT2', _FLUA.millitime() - t0)\n"
            "  _FLUA.exit(0)\n"
            "end, 500)"
        )
        await wait_until(lambda: not engine.is_running(), timeout=2)
        real_elapsed = time.monotonic() - start
        assert real_elapsed < 0.4  # 500 virtual ms at 10x ≈ 50 real ms
        out = capsys.readouterr().out
        assert "FAST" in out
        match = re.search(r"DT2\t(\d+)", out)
        assert match, out
        virtual_dt = float(match.group(1))
        assert 300 < virtual_dt < 700  # virtual time still ran the full 0.5 s
    finally:
        await engine.stop()


def test_run_for_negative_instant_stops_at_virtual_limit() -> None:
    # --instant --run-for -5: five simulated seconds — the 1000 ms interval
    # fires exactly five times and the process exits in milliseconds of wall
    # time (this used to be 5 wall seconds of unbounded firing). Count the
    # marker, not the payload "42": the QA log lines carry timestamps that
    # can themselves contain "42" (e.g. runs spanning minute :42).
    start = time.monotonic()
    result = _run_cli(
        "--color",
        "never",
        "--instant",
        "--run-for",
        "-5",
        "-e",
        "setInterval(function() print('FIRE42') end,1000)",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert time.monotonic() - start < 3.0  # instant, not 5 wall seconds
    assert result.stdout.count("FIRE42") == 5  # exactly five virtual seconds


def test_run_for_negative_speed_uses_virtual_seconds() -> None:
    # --speed 10 --run-for -1: one virtual second at 10x ≈ 100 ms wall —
    # the 500 ms timer fires inside the limit and the run ends well before
    # one wall second (the old wall-based fixed run took a full wall second)
    start = time.monotonic()
    result = _run_cli(
        "--color",
        "never",
        "--speed",
        "10",
        "--run-for",
        "-1",
        "-e",
        "setTimeout(function() print('FIRED') end, 500)",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert time.monotonic() - start < 0.8  # ~100 ms, not a full wall second
    assert "FIRED" in result.stdout


def test_run_for_negative_instant_with_no_timers_still_exits() -> None:
    # virtual time cannot advance with nothing left to fire — the wall bound
    # ends the run instead of hanging forever
    start = time.monotonic()
    result = _run_cli(
        "--color",
        "never",
        "--instant",
        "--run-for",
        "-2",
        "-e",
        "print('HI')",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert time.monotonic() - start < 10.0  # bounded by the 2 s wall fallback


def test_run_for_negative_realtime_still_wall_seconds() -> None:
    # realtime is unchanged: virtual time tracks the wall clock, so a fixed
    # run of -1 lasts about one wall second
    start = time.monotonic()
    result = _run_cli("--color", "never", "--run-for", "-1", "-e", "print('HI')")
    assert result.returncode == 0, result.stdout + result.stderr
    assert 0.8 <= time.monotonic() - start < 3.0
