"""QuickApp model: isolated environments, per-QA timers, config copy."""

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


async def wait_until(predicate, timeout: float = 3.0) -> None:
    import asyncio

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.01)


def qa_timer_count(engine: LuaEngine, qa_id: int) -> int:
    return engine.lua_runtime().globals()["_FLUA"]["qaTimerCount"](qa_id)


@pytest.mark.asyncio
async def test_qa_environments_are_isolated(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text("x = 'from-a'\nsetTimeout(function() print('A', x) end, 20)\n")
    b = tmp_path / "b.lua"
    b.write_text("x = 'from-b'\nsetTimeout(function() print('B', x) end, 20)\n")
    engine = LuaEngine()
    await engine.start()
    try:
        id_a = engine.start_qa(str(a), None, {}, str(a))
        id_b = engine.start_qa(str(b), None, {}, str(b))
        assert id_a == 5000  # engine-assigned ids start at 5000
        assert id_b == 5001
        await wait_until(lambda: not engine.has_pending_work())
        # Python-side QA directory: ids in start order, resolved names, status
        assert engine.qa_ids() == [id_a, id_b]
        assert engine.qa_info(id_a)["name"] == "a"  # basename without suffix
        assert engine.qa_info(id_a)["loaded"] is True
        assert engine.qa_info(id_b)["name"] == "b"
        assert engine.qa_instance(id_a).name == "a"
        out = capsys.readouterr().out
        assert "A from-a" in out
        assert "B from-b" in out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_qa_timers_are_tracked(tmp_path) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "setTimeout(function() end, 400)\nsetTimeout(function() end, 800)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text("setTimeout(function() end, 300)\n")
    engine = LuaEngine()
    await engine.start()
    try:
        id_a = engine.start_qa(str(a), None, {}, str(a))
        id_b = engine.start_qa(str(b), None, {}, str(b))
        # after the 0 ms bootstrap timers fire and the QAs schedule their
        # own timers, QA a tracks two and QA b tracks one
        await wait_until(
            lambda: qa_timer_count(engine, id_a) == 2
            and qa_timer_count(engine, id_b) == 1
        )
        await wait_until(lambda: not engine.has_pending_work())
        assert qa_timer_count(engine, id_a) == 0  # fired timers untrack
        assert qa_timer_count(engine, id_b) == 0
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_qa_config_copy(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text("print('CFG', config.name, config.speed)\n")
    engine = LuaEngine(speed=2.0, config={"speed": 2.0})
    await engine.start()
    try:
        # the CLI merges global config + the QA's local params into the copy
        engine.start_qa(str(a), None, {"speed": 2.0, "name": "qa-a"}, str(a))
        await wait_until(lambda: not engine.has_pending_work())
        assert "CFG qa-a 2.0" in capsys.readouterr().out
    finally:
        await engine.stop()


def test_cli_runs_multiple_qas_isolated(tmp_path) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "--%%name:qa-a\n"
        "x = 'a'\n"
        "setTimeout(function() print('A', x, config.name) end, 20)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "--%%name:qa-b\n"
        "--%%instant:true\n"  # global param: copied up, last file wins
        "x = 'b'\n"
        "setTimeout(function() print('B', x, config.name); exit(0) end, 3600000)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(a), str(b)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A a qa-a" in result.stdout
    assert "B b qa-b" in result.stdout


def test_fibaro_log_lines_are_hc3_styled(tmp_path) -> None:
    script = tmp_path / "log.lua"
    script.write_text(
        'fibaro.debug("TAG", "Test debug")\n'
        'fibaro.trace("TAG", "Test trace")\n'
        'fibaro.warning("TAG", "Test warning")\n'
        'fibaro.error("TAG", "Test error")\n'
        "exit(0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    stamp = r"\[\d{2}\.\d{2}\.\d{4}\]\[\d{2}:\d{2}:\d{2}\]"
    plain_text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert re.search(stamp + r"\[DEBUG  \]\[TAG\]: Test debug", plain_text)
    assert re.search(stamp + r"\[TRACE  \]\[TAG\]: Test trace", plain_text)
    assert re.search(stamp + r"\[WARNING\]\[TAG\]: Test warning", plain_text)
    assert re.search(stamp + r"\[ERROR  \]\[TAG\]: Test error", plain_text)
    # plua-style palette: green DEBUG, cyan TRACE, orange WARNING, red ERROR,
    # gray date/tag — colors are on by default
    assert "\x1b[32m" in result.stdout
    assert "\x1b[36m" in result.stdout
    assert "\x1b[33m" in result.stdout
    assert "\x1b[31;1m" in result.stdout
    assert "\x1b[37m" in result.stdout

    # --color never produces plain output
    plain = subprocess.run(
        [sys.executable, "-m", "flua", "--color", "never", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert plain.returncode == 0
    assert "\x1b[" not in plain.stdout


def test_startup_greeting(tmp_path) -> None:
    script = tmp_path / "greet.lua"
    script.write_text("exit(0)\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"flua \d+\.\d+\.\d+", result.stdout)
    assert re.search(r"Lua 5\.\d+", result.stdout)
    assert re.search(r"Python 3\.\d+", result.stdout)

    # --nogreet suppresses the greeting
    quiet = subprocess.run(
        [sys.executable, "-m", "flua", "--nogreet", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert quiet.returncode == 0
    assert "flua 0.1.0, Lua" not in quiet.stdout


def test_example_qa_pair_runs_together() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flua",
            str(REPO_ROOT / "examples" / "qa1.lua"),
            str(REPO_ROOT / "examples" / "qa2.lua"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "qa-one: 1" in result.stdout
    assert "qa-two: 100" in result.stdout
    assert "qa-one: 2" in result.stdout
    assert "qa-two: 200" in result.stdout
