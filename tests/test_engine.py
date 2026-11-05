"""Integration tests through a real lupa VM: message round-trips, timers, exit."""

import asyncio
import io
import time
from collections.abc import Callable

import pytest

pytest.importorskip("lupa")

from flua import messages  # noqa: E402
from flua.engine import LuaEngine  # noqa: E402


async def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_print_roundtrip(capsys) -> None:
    engine = LuaEngine()
    await engine.start()
    engine.execute("print('hello', 42)")
    await wait_until(lambda: not engine.has_pending_work())
    assert "hello\t42" in capsys.readouterr().out
    await engine.stop()


@pytest.mark.asyncio
async def test_timeout_fires_callback(capsys) -> None:
    engine = LuaEngine()
    await engine.start()
    engine.execute("setTimeout(function() print('fired') end, 50)")
    await wait_until(lambda: not engine.has_pending_work())
    assert "fired" in capsys.readouterr().out
    await engine.stop()


@pytest.mark.asyncio
async def test_clear_timeout(capsys) -> None:
    engine = LuaEngine()
    await engine.start()
    engine.execute(
        "local id = setTimeout(function() print('nope') end, 80)\n"
        "setTimeout(function() clearTimeout(id) end, 10)"
    )
    await wait_until(lambda: not engine.has_pending_work())
    assert "nope" not in capsys.readouterr().out
    await engine.stop()


@pytest.mark.asyncio
async def test_interval_then_clear_and_exit(capsys) -> None:
    engine = LuaEngine()
    await engine.start()
    engine.execute(
        "local n = 0\n"
        "local iv\n"  # declare first: the callback reads iv, so it must be in scope
        "iv = setInterval(function()\n"
        "  n = n + 1\n"
        "  print('tick', n)\n"
        "  if n >= 3 then clearInterval(iv); _FLUA.exit(0) end\n"
        "end, 20)"
    )
    await wait_until(lambda: not engine.is_running())
    await engine.stop()
    assert engine.exit_code == 0
    assert "tick\t3" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_pump_idle_poll_adapts_to_timers() -> None:
    # the pump's idle sleep: long when no timers are pending (an idle run
    # must not spin at 10 ms), tight when a timer exists (virtual-clock
    # deadline precision — the timing-sensitive tests depend on it)
    engine = LuaEngine()
    await engine.start()
    try:
        assert engine._idle_poll_delay() == 0.05
        engine.execute("setTimeout(function() end, 100000)")
        # the setTimeout message rides the inbound queue to the pump
        await asyncio.sleep(0.1)
        assert engine._idle_poll_delay() == 0.01
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_exit_message_sets_exit_code() -> None:
    engine = LuaEngine()
    await engine.start()
    engine.execute("_FLUA.exit(7)")
    await wait_until(lambda: not engine.is_running())
    await engine.stop()
    assert engine.exit_code == 7


@pytest.mark.asyncio
async def test_flua_keep_alive_counts_without_timers() -> None:
    # _FLUA.keepAlive(): the flag alone (no timers) keeps the run alive in
    # every mode — the mechanism behind the bundled sim devices
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(None, "_FLUA.keepAlive()\n", {}, "keeper")
        await asyncio.sleep(0.1)
        assert engine.has_pending_work()  # no timers at all: the flag counts
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_flua_keep_alive_clears_on_qa_exit(capsys) -> None:
    # the QA's own exit clears its keep-alive flag, so the run can drain
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(
            None,
            "_FLUA.keepAlive()\n"
            "setTimeout(function() print('EXITING'); os.exit() end, 20)\n",
            {},
            "keeper",
        )
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    assert "EXITING" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_error_in_callback_does_not_kill_engine(capsys) -> None:
    engine = LuaEngine()
    await engine.start()
    engine.execute(
        "setTimeout(function() error('boom') end, 10)\n"
        "setTimeout(function() print('still alive') end, 60)"
    )
    await wait_until(lambda: not engine.has_pending_work())
    out = capsys.readouterr().out
    assert "boom" in out
    assert "still alive" in out
    await engine.stop()


@pytest.mark.asyncio
async def test_zero_delay_main_style_bootstrap(capsys) -> None:
    """The CLI pattern: user code wrapped in a 0 ms setTimeout."""
    engine = LuaEngine()
    await engine.start()
    engine.execute(
        "setTimeout(function()\n"
        "  print('main ran')\n"
        "  setTimeout(function() print('child ran') end, 30)\n"
        "end, 0)"
    )
    await wait_until(lambda: not engine.has_pending_work())
    out = capsys.readouterr().out
    assert "main ran" in out
    assert "child ran" in out
    await engine.stop()


def test_log_line_prints_immediately_without_pump(capsys) -> None:
    # QA logs call _PY.log directly (no message queue): output is immediate
    # even when the pump is not running at all — which is exactly what makes
    # prints visible while the VS Code debugger holds the main thread.
    engine = LuaEngine()
    engine.log_line("info", "IMMEDIATE")
    assert "IMMEDIATE" in capsys.readouterr().out
    assert not engine._inbound  # never queued


def test_log_line_escapes_characters_unsupported_by_stdout(monkeypatch) -> None:
    class Cp1252Stream(io.StringIO):
        @property
        def encoding(self) -> str:
            return "cp1252"

        def write(self, text: str) -> int:
            text.encode(self.encoding)
            return super().write(text)

    stream = Cp1252Stream()
    monkeypatch.setattr("sys.stdout", stream)

    LuaEngine().log_line("info", "🚀 flua")

    assert stream.getvalue() == "\\U0001f680 flua\n"


def test_log_message_from_engine_still_queues(capsys) -> None:
    # engine-side messages.log still rides the pump (e.g. greeting ordering)
    engine = LuaEngine()
    engine.post(messages.log("info", "QUEUED"))
    assert "QUEUED" not in capsys.readouterr().out
    assert len(engine._inbound) == 1


def test_api_result_handoff_is_atomic() -> None:
    # ADR 0006 amendment: the api-result handoff (enqueue + inflight
    # decrement) must run together on the pump loop — never "counter zero,
    # result not yet queued", the window where the CLI's idle poll ended a
    # run between a returned api.* call and its delivery (dev/hc3_api_filter
    # test.lua quitting silently in online mode).
    engine = LuaEngine()
    captured: list = []

    class FakeLoop:
        def call_soon_threadsafe(self, fn, *_a, **_k):
            captured.append(fn)  # deferred, like the real loop

    engine._loop = FakeLoop()
    engine.api.dispatch = lambda method, url, body, qa_id=None: ({"x": 1}, 200)
    engine._handle_api_call(
        {"type": messages.API_CALL, "qa": 0, "method": "GET", "url": "/x", "body": None}
    )
    deadline = time.monotonic() + 3.0
    while not captured and time.monotonic() < deadline:
        time.sleep(0.001)
    assert captured, "the worker never handed the result over"
    # the handoff is scheduled but not yet run: the counter must still hold
    # the run open — otherwise has_pending_work() sees idle and the CLI exits
    assert engine._api_calls_inflight == 1
    assert engine.has_pending_work()
    captured[0]()  # the pump loop runs the handoff
    assert engine._api_calls_inflight == 0
    assert engine.has_pending_work()  # the result is now in the outbound queue
    assert engine._outbound.get_nowait()["type"] == messages.API_RESULT


@pytest.mark.asyncio
async def test_flua_main_path_reads_sibling_files(tmp_path, capsys) -> None:
    # _FLUA.mainPath: the main QA file's directory with a trailing
    # separator — a require'd sibling module (the climateEndPoint pattern)
    # opens data shipped next to the QA regardless of the cwd
    (tmp_path / "data.txt").write_text("zone-42")
    (tmp_path / "endpoint.lua").write_text(
        "local M = {}\n"
        "function M.load()\n"
        "  local f = io.open(_FLUA.mainPath .. 'data.txt', 'r')\n"
        "  local s = f:read('*a') f:close()\n"
        "  return s\n"
        "end\n"
        "return M\n"
    )
    script = tmp_path / "qa.lua"
    script.write_text(
        "local ep = require('endpoint')\n"
        "function QuickApp:onInit()\n"
        "  print('MAINPATH', _FLUA.mainPath)\n"
        "  print('DATA', ep.load())\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        assert qa_id is not None
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "DATA zone-42" in out
    assert "MAINPATH " + str(tmp_path) + "/" in out
