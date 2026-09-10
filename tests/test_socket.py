"""Lua-level socket tests: the socket.lua facade and the debugger CLI."""

import socket
import subprocess
import sys
import threading
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
        await _sleep_async()


async def _sleep_async() -> None:
    import asyncio

    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_socket_lua_roundtrip(echo_server, capsys) -> None:
    engine = LuaEngine()
    await engine.start()
    try:
        engine.execute(
            f"""
local socket = require("socket")
assert(type(socket.tcp) == "function", "socket.tcp missing")
local c = socket.tcp()
c:settimeout(2)
assert(c:connect("127.0.0.1", {echo_server.port}) == 1)
assert(c:send("hello\\n") == 6)
local line = c:receive("*l")
assert(line == "hello", "expected hello, got " .. tostring(line))
-- send with a range: only bytes 3..5 of the string go on the wire
assert(c:send("0123456789", 3, 5) == 3)
local d = c:receive(3)
assert(d == "234", "expected 234, got " .. tostring(d))
local ip, port = c:getsockname()
assert(type(ip) == "string" and type(port) == "number", "getsockname")
c:close()
print("SOCKET_OK")
"""
        )
        await wait_until(lambda: not engine.has_pending_work())
        assert "SOCKET_OK" in capsys.readouterr().out
    finally:
        await engine.stop()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run_flua(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_debugger_without_listener_runs_normally(tmp_path) -> None:
    script = tmp_path / "dbg_plain.lua"
    script.write_text('print("PLAIN_OK")\nexit(0)\n')
    result = _run_flua("--debugger", str(_free_port()), str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PLAIN_OK" in result.stdout
    # mobdebug reports its own connection failure and the program still runs
    assert "Could not connect" in result.stdout


def test_mobdebug_port_env_starts_debugger(tmp_path, monkeypatch) -> None:
    # the VS Code mobdebug extension launches the interpreter with
    # MOBDEBUG_PORT set; flua must honor it like --debugger
    script = tmp_path / "env_dbg.lua"
    script.write_text('print("ENV_OK")\nexit(0)\n')
    monkeypatch.setenv("MOBDEBUG_PORT", str(_free_port()))
    result = _run_flua(str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ENV_OK" in result.stdout
    assert "Could not connect" in result.stdout  # the debugger tried to attach


def test_debugger_fake_ide_roundtrip(tmp_path) -> None:
    script = tmp_path / "dbg.lua"
    script.write_text(
        'print("DBG_START")\n'
        "local t0 = os.time()\n"
        "setTimeout(function()\n"
        "  require('mobdebug').pause()  -- stops here; fake IDE holds the connection\n"
        "  local dt = os.time() - t0\n"
        "  print(string.format('VTIME_%s', tostring(dt < 1)))\n"
        "  print('AFTER_PAUSE')\n"
        "  exit(0)\n"
        "end, 100)\n"
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    events: list[str] = []
    received: list[bytes] = []

    def fake_ide() -> None:
        listener.settimeout(20)
        try:
            conn, _ = listener.accept()
        except TimeoutError:
            return
        events.append("connected")
        time.sleep(2.0)  # let mobdebug settle (protocol detection)
        try:
            # classic protocol: the first RUN announces the pause ("200 OK" +
            # "202 Paused"), the second RUN resumes the program
            conn.sendall(b"RUN\n")
            time.sleep(0.5)
            conn.sendall(b"RUN\n")
            conn.settimeout(0.5)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    data = conn.recv(4096)
                except TimeoutError:
                    continue
                except OSError:
                    break
                if not data:
                    break
                received.append(data)
        finally:
            conn.close()
            listener.close()

    thread = threading.Thread(target=fake_ide, daemon=True)
    thread.start()
    result = _run_flua("--debugger", str(port), str(script))
    thread.join(timeout=25)

    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert events == ["connected"], f"debuggee never connected: {events}"
    ide_saw = b"".join(received).decode("utf-8", errors="replace")
    # the program prints (possibly redirected to the debugger) and completes
    assert "AFTER_PAUSE" in result.stdout or "AFTER_PAUSE" in ide_saw, (
        f"stdout:\n{result.stdout}\nide saw:\n{ide_saw}"
    )
    # virtual time must not include the debugger pause (~2.5 s held by the
    # fake IDE): os.time() stays put while paused at a breakpoint
    assert "VTIME_true" in result.stdout or "VTIME_true" in ide_saw, (
        f"virtual time advanced during the debugger pause\n"
        f"stdout:\n{result.stdout}\nide saw:\n{ide_saw}"
    )
