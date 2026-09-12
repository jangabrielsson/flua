"""QuickApp model: isolated environments, per-QA timers, config copy."""

import asyncio
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
    return engine.qa_timer_count(qa_id)


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
    a.write_text("print('CFG', _FLUA.config.name, _FLUA.config.speed)\n")
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
        "setTimeout(function() print('A', x, _FLUA.config.name) end, 20)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "--%%name:qa-b\n"
        "--%%instant:true\n"  # global param: copied up, last file wins
        "x = 'b'\n"
        "setTimeout(function() print('B', x, _FLUA.config.name); exit(0) end, 3600000)\n"
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


def test_examples_qa_pair_calls_each_other() -> None:
    # examples/qa3.lua + qa4.lua: QAs find each other by name and drive each
    # other through fibaro.call (device actions via the pump).
    result = subprocess.run(
        [sys.executable, "-m", "flua", "examples/qa3.lua", "examples/qa4.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "qa4: turning qa-three on" in result.stdout
    assert "qa3: turned on" in result.stdout
    assert "qa4: got qa3 is on" in result.stdout
    assert "qa4: turning qa-three off" in result.stdout
    assert "qa3: turned off" in result.stdout


# -- dynamic loading (loadQAfromFile / loadQAfromString) ------------------------


@pytest.mark.asyncio
async def test_dynamic_load_from_file(tmp_path, capsys) -> None:
    target = tmp_path / "loaded.lua"
    target.write_text(
        "--%%name:loaded-qa\n"
        "--%%type:com.fibaro.remoteColorController\n"
        "function QuickApp:turnOn() print('LOADED ON', self.id) end\n"
    )
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        "  local id, err = _FLUA.loadQAfromFile('" + str(target) + "')\n"
        "  print('GOT', id, err)\n"
        "  if id then\n"
        "    fibaro.call(id, 'turnOn') -- same callback: must reach the new QA\n"
        "    local dev = api.get('/devices/'..id)\n"
        "    print('DEV', dev.name, dev.type, dev.roomID)\n"
        "  end\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "GOT 5001" in out
    assert "LOADED ON 5001" in out
    # --%% annotations from the loaded file drive name/type; the type
    # skeleton supplies the default room
    assert "DEV loaded-qa com.fibaro.remoteColorController 219" in out


@pytest.mark.asyncio
async def test_dynamic_load_from_string(tmp_path, capsys) -> None:
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        "  local id, err = _FLUA.loadQAfromString([[\n"
        "function QuickApp:setValue(v) print('STR QA', v) end\n"
        "]])\n"
        "  print('STRID', id, err)\n"
        "  fibaro.call(id, 'setValue', 42)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        await asyncio.sleep(0.4)
        assert engine._temp_qa_paths == set()  # temp file consumed and removed
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "STRID 5001" in out
    assert "STR QA 42" in out


@pytest.mark.asyncio
async def test_inline_qa_directives_do_not_leak(tmp_path, capsys) -> None:
    # --%% lines inside an inline QA string must not bleed into the outer
    # QA's config; the EOH comment ends the outer header (plua convention).
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "--%%name:outer\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function()\n"
        "  print('OUTER', _FLUA.config.name)\n"
        "  local id = _FLUA.loadQAfromString([[\n"
        "--%%name:inner\n"
        "function QuickApp:onInit() print('INNER', _FLUA.config.name) end\n"
        "]])\n"
        "  local dev = api.get('/devices/'..id)\n"
        "  print('INNERDEV', dev.name)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(loader))  # parses the --%% header (EOH-aware)
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "OUTER outer" in out  # not overwritten by the inner --%%name
    assert "INNER inner" in out  # the inner QA parsed its own header
    assert "INNERDEV inner" in out


@pytest.mark.asyncio
async def test_dynamic_load_missing_file(tmp_path, capsys) -> None:
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        "  local id, err = _FLUA.loadQAfromFile('/no/such/file.lua')\n"
        "  print('ERR', id == nil, err ~= nil)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        await asyncio.sleep(0.3)
    finally:
        await engine.stop()
    assert "ERR true true" in capsys.readouterr().out


def test_example_dynamic_loading() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "flua", "examples/dynamic.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "file load: 5001" in result.stdout
    assert "string load: 5002" in result.stdout
    assert "qa3: turned on" in result.stdout
    assert "string QA: pong" in result.stdout
    assert "inline name: inline-qa" in result.stdout


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


def test_print_binary_string_does_not_crash(tmp_path) -> None:
    # utf8.charpattern is a binary pattern (raw bytes, not valid UTF-8).
    # Printing it must not take the process down: the message bridge
    # hex-escapes invalid UTF-8 instead of raising during lupa's strict
    # decode (regression: UnicodeDecodeError -> exit code 1).
    result = subprocess.run(
        [sys.executable, "-m", "flua", "-e", "print(utf8.charpattern)"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plain_text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert r"[\x00-\x7F\xC2-\xFD][\x80-\xBF]*" in plain_text
    assert "stack traceback" not in plain_text


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


def test_exit_terminates_only_the_calling_qa(tmp_path) -> None:
    # HC3 semantics: exit() terminates the QA that called it (each QA is its
    # own process on the HC3; flua runs them cooperatively). Its timers are
    # cancelled; the other QAs keep running.
    a = tmp_path / "a.lua"
    a.write_text(
        "print('A_START')\n"
        "setTimeout(function() print('A_LATE') end, 100)\n"  # cancelled on exit
        "setTimeout(function() print('A_EXIT'); exit(0) end, 10)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "setTimeout(function() print('B_DONE'); exit(0) end, 200)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(a), str(b)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A_START" in result.stdout
    assert "A_EXIT" in result.stdout
    assert "A_LATE" not in result.stdout  # the QA's timers died with it
    assert "B_DONE" in result.stdout  # the other QA kept running


def test_exit_code_from_failing_qa_becomes_engine_exit_code(tmp_path) -> None:
    # a QA exiting nonzero marks the run failed (last failing QA wins)
    script = tmp_path / "failing.lua"
    script.write_text("setTimeout(function() exit(7) end, 10)\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 7, result.stdout + result.stderr


def test_flua_table_is_per_qa(tmp_path) -> None:
    # each QA has its own _FLUA: qaId/config/arg are stable per QA even in
    # deferred reads, while the API itself is the shared engine table
    a = tmp_path / "a.lua"
    a.write_text(
        "--%%name:qa-a\n"
        "setTimeout(function()\n"
        "  print('A', _FLUA.qaId, _FLUA.config.name)\n"
        "  exit(0)\n"
        "end, 30)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "--%%name:qa-b\n"
        "setTimeout(function()\n"
        "  print('B', _FLUA.qaId, _FLUA.config.name)\n"
        "  exit(0)\n"
        "end, 30)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(a), str(b)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A 5000 qa-a" in result.stdout
    assert "B 5001 qa-b" in result.stdout