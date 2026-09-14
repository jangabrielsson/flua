"""Engine-level tests for virtual time modes (instant / accelerated)."""

import math
import re
import time

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402


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