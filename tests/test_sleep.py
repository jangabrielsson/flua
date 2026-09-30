"""fibaro.sleep: per-QA suspension; messages defer and run after the sleep."""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


async def wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.01)


async def wait_for_output(capsys, needle: str, timeout: float = 3.0) -> str:
    """Accumulate stdout until ``needle`` appears (capsys reads consume)."""
    seen = ""
    deadline = time.monotonic() + timeout
    while needle not in seen:
        if time.monotonic() > deadline:
            raise AssertionError(f"{needle!r} not printed; saw: {seen}")
        seen += capsys.readouterr().out
        await asyncio.sleep(0.01)
    return seen


@pytest.mark.asyncio
async def test_timers_during_sleep_run_after_the_sleeping_callback(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "setTimeout(function()\n"
        "  print('A-BEFORE')\n"
        "  fibaro.sleep(200)\n"
        "  print('A-AFTER')\n"
        "end, 10)\n"
        "-- due while A sleeps: deferred, runs after the callback resumed\n"
        "setTimeout(function() print('A-DEFERRED') end, 100)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text("setTimeout(function() print('B-RAN') end, 100)\n")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        engine.start_qa(str(b), None, {}, str(b))
        await wait_until(lambda: not engine.has_pending_work())
        out = capsys.readouterr().out
        assert "A-BEFORE" in out and "A-AFTER" in out
        assert "B-RAN" in out  # the other QA ran during the sleep
        # the sleeping callback resumed first, then the deferred timer
        assert "A-DEFERRED" in out
        assert out.index("A-AFTER") < out.index("A-DEFERRED")
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_device_action_during_sleep_runs_after_resume(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "setTimeout(function()\n"
        "  fibaro.sleep(300)\n"
        "  print('A-WOKE')\n"
        "end, 10)\n"
        "function QuickApp:turnOn() print('TURNED-ON') end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        await asyncio.sleep(0.1)  # A is sleeping now (wakes at ~310ms)
        engine.api.dispatch("POST", "/devices/5000/action/turnOn", {})
        seen = await wait_for_output(capsys, "TURNED-ON")
        # the sleeping callback resumed first, then the deferred action
        assert "A-WOKE" in seen
        assert seen.index("A-WOKE") < seen.index("TURNED-ON")
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_sleep_is_virtual_time_instant_collapses_it(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "setTimeout(function()\n"
        "  fibaro.sleep(60 * 1000)\n"  # a minute; --instant collapses it
        "  print('A-DONE')\n"
        "end, 10)\n"
    )
    engine = LuaEngine(speed=float("inf"))
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        await wait_until(lambda: not engine.has_pending_work())
        out = capsys.readouterr().out
        assert "A-DONE" in out
        # instant mode jumps virtual time to the sleep deadline
        assert engine.clock.time >= 60.0
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_sleep_at_top_level_errors(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text("fibaro.sleep(100)\n")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        await asyncio.sleep(0.3)
        assert engine.exit_code == 1  # load failed
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "fibaro.sleep" in out  # the error names the API


@pytest.mark.asyncio
async def test_error_after_sleep_is_contained(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "setTimeout(function()\n"
        "  fibaro.sleep(50)\n"
        "  error('BOOM-AFTER-SLEEP')\n"
        "end, 10)\n"
        "setTimeout(function() print('A-STILL-ALIVE') end, 100)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        await wait_until(lambda: not engine.has_pending_work())
        out = capsys.readouterr().out
        assert "BOOM-AFTER-SLEEP" in out  # error printed with traceback
        assert "A-STILL-ALIVE" in out  # the QA survived the error
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_restart_during_sleep_drops_deferred_messages(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "function QuickApp:onInit() print('BOOTED') end\n"
        "function QuickApp:startSleep()\n"
        "  fibaro.sleep(60 * 1000)\n"
        "  print('OLD-WOKE')\n"
        "end\n"
        "function QuickApp:turnOn() print('TURNED-ON') end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        await wait_for_output(capsys, "BOOTED")
        capsys.readouterr()  # drain
        engine.api.dispatch("POST", "/devices/5000/action/startSleep", {})
        await asyncio.sleep(0.1)  # the QA is now sleeping
        engine.api.dispatch("POST", "/devices/5000/action/turnOn", {})  # deferred
        await asyncio.sleep(0.1)
        engine.restart_qa(5000)
        await wait_for_output(capsys, "BOOTED")
        await asyncio.sleep(0.2)
        out = capsys.readouterr().out
        assert "OLD-WOKE" not in out  # the old sleep never resumes
        assert "TURNED-ON" not in out  # deferred message died with the old instance
        # the fresh instance delivers actions normally
        engine.api.dispatch("POST", "/devices/5000/action/turnOn", {})
        await wait_for_output(capsys, "TURNED-ON")
    finally:
        await engine.stop()


def test_example_sleep_keeps_deferred_timer() -> None:
    # examples/sleep.lua sets a 2s timer and sleeps 3s: the timer is due
    # during the sleep, so it must run after the sleeping callback resumed
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/sleep.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Test 1 executed, 2s later" in result.stdout
    assert "Slept for 3 seconds in onInit" in result.stdout
    assert result.stdout.index("Slept for 3 seconds") < result.stdout.index("Test 1 executed")
    assert "stack traceback" not in result.stdout
