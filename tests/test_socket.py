"""Lua-level socket tests: the socket.lua facade and the debugger CLI."""

import json
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


def test_debugger_flag_with_script_uses_default_port() -> None:
    # `flua --debugger script.lua` (the VS Code launch config form): the
    # optional port must not eat the script as its value
    from flua.cli import _normalize_debugger_argv

    assert _normalize_debugger_argv(["--debugger", "qa.lua"]) == ["qa.lua", "--debugger"]
    assert _normalize_debugger_argv(["--debugger", "a.lua", "b.lua"]) == [
        "a.lua",
        "b.lua",
        "--debugger",
    ]
    # an explicit port stays where it is
    assert _normalize_debugger_argv(["--debugger", "8173", "a.lua"]) == [
        "--debugger",
        "8173",
        "a.lua",
    ]
    assert _normalize_debugger_argv(["a.lua", "--debugger"]) == ["a.lua", "--debugger"]
    assert _normalize_debugger_argv(["--debugger", "-e", "print(1)"]) == [
        "--debugger",
        "-e",
        "print(1)",
    ]


def test_debugger_flag_with_script_end_to_end(tmp_path) -> None:
    # the exact form the VS Code launch config produces: --debugger then the
    # script, no explicit port (8172). A fake IDE answers on the default port.
    script = tmp_path / "dbg_default.lua"
    script.write_text(
        'print("DEF_START")\n'
        "setTimeout(function()\n"
        "  require('mobdebug').pause()\n"
        "  print('DEF_AFTER_PAUSE')\n"
        "  exit(0)\n"
        "end, 100)\n"
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 8172))
    listener.listen(1)

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
    result = _run_flua("--debugger", str(script))  # no explicit port
    thread.join(timeout=25)

    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert events == ["connected"], f"debuggee never connected: {events}"
    ide_saw = b"".join(received).decode("utf-8", errors="replace")
    assert "DEF_AFTER_PAUSE" in result.stdout or "DEF_AFTER_PAUSE" in ide_saw, (
        f"stdout:\n{result.stdout}\nide saw:\n{ide_saw}"
    )


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


def _vsc_frame(obj: dict) -> bytes:
    """One #<len>\\n<json> message (mobdebug's VSCODE debugger protocol)."""
    data = json.dumps(obj).encode("utf-8")
    return b"#" + str(len(data)).encode() + b"\n" + data


def _vsc_read(conn: socket.socket) -> dict | None:
    header = b""
    while not header.endswith(b"\n"):
        byte = conn.recv(1)
        if not byte:
            return None
        header += byte
    length = int(header.strip().lstrip(b"#"))
    body = b""
    while len(body) < length:
        chunk = conn.recv(length - len(body))
        if not chunk:
            return None
        body += chunk
    return json.loads(body.decode("utf-8"))


def _vsc_response(conn: socket.socket, seq: int, timeout: float = 10.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = _vsc_read(conn)
        if msg is None:
            return None
        if msg.get("type") == "response" and msg.get("request_seq") == seq:
            return msg
    return None


def test_debugger_vscode_protocol_breakpoint_stop(tmp_path) -> None:
    """The VS Code mobdebug extension's protocol: breakpoints stop the program.

    The extension (alexeymelnichuk.lua-mobdebug) does not set MOBDEBUG_PORT or
    pass --debugger itself; it listens on listenPort and waits for the
    debuggee to connect, then speaks the #-framed JSON "VSCODE" protocol:
    welcome -> setBreakpoints -> configurationDone, and it only sends
    continue after a 'stopped' event. This test replays that exchange and
    asserts the program stops at the breakpoint line.
    """
    script = tmp_path / "vsc.lua"
    script.write_text(
        'print("VSC_START")\n'
        "local x = 1\n"  # line 2 — breakpoint
        "local y = x + 1\n"  # line 3
        'print("VSC_END", y)\n'
        "exit(0)\n"
    )
    # use the symlink-resolved path everywhere: the CLI resolves the script
    # to a real path for loadfile, and breakpoints must match against it
    base = str(tmp_path.resolve())
    script_path = str(script.resolve())

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    events: list[str] = []
    top_frame: dict = {}

    def fake_ide() -> None:
        listener.settimeout(20)
        try:
            conn, _ = listener.accept()
        except TimeoutError:
            return
        events.append("connected")
        try:
            conn.sendall(_vsc_frame({
                "command": "welcome",
                "arguments": {
                    "sourceBasePath": base,
                    "stopOnEntry": False,
                    "directorySeperator": "/",
                    "pathMap": [],
                },
            }))
            time.sleep(0.3)
            conn.sendall(_vsc_frame({
                "seq": 1,
                "type": "request",
                "command": "setBreakpoints",
                "arguments": {
                    "source": {"path": script_path},
                    "breakpoints": [{"line": 2}],
                },
            }))
            resp = _vsc_response(conn, 1)
            events.append(f"setBreakpoints:{bool(resp and resp.get('success'))}")
            conn.sendall(_vsc_frame({
                "seq": 2, "type": "request", "command": "configurationDone",
            }))
            resp = _vsc_response(conn, 2)
            events.append(f"configurationDone:{bool(resp and resp.get('success'))}")
            # like the real IDE: no continue yet — the next message must be
            # the 'stopped' event at the breakpoint
            conn.settimeout(10.0)
            while True:
                msg = _vsc_read(conn)
                if msg is None:
                    break
                if msg.get("type") == "event" and msg.get("event") == "stopped":
                    events.append(f"stopped:{msg['body'].get('reason')}")
                    conn.sendall(_vsc_frame({
                        "seq": 3,
                        "type": "request",
                        "command": "stackTrace",
                        "arguments": {"threadId": 0, "startFrame": 0, "levels": 2},
                    }))
                    resp = _vsc_response(conn, 3)
                    frames = ((resp or {}).get("body") or {}).get("stackFrames") or []
                    if frames:
                        top_frame["path"] = frames[0]["source"]["path"]
                        top_frame["line"] = frames[0]["line"]
                    conn.sendall(_vsc_frame({
                        "seq": 4, "type": "request", "command": "continue",
                    }))
                    break
        finally:
            conn.close()
            listener.close()

    thread = threading.Thread(target=fake_ide, daemon=True)
    thread.start()
    result = _run_flua("--debugger", str(port), str(script))
    thread.join(timeout=25)

    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert events and events[0] == "connected", f"debuggee never connected: {events}"
    assert "stopped:breakpoint" in events, f"no breakpoint stop: {events}"
    assert "VSC_END" in result.stdout, "program did not finish after resume"
    assert "Warning: mobdebug failed" not in result.stdout, result.stdout
    # the stop is at the breakpoint line in the script (paths are normalized
    # against sourceBasePath, lowercased on case-insensitive filesystems)
    assert top_frame.get("path", "").endswith("/vsc.lua"), top_frame
    assert top_frame.get("line") == 2, top_frame


def test_lua_cli_compat_flags(tmp_path) -> None:
    # the VS Code mobdebug extension launches interpreters with
    # `-l package -e "<debugger bootstrap>" script.lua`; flua must accept -l
    # (ignored, like the Lua CLI) and run the -e code before the script
    script = tmp_path / "compat.lua"
    script.write_text('print("SCRIPT_OK")\nexit(0)\n')
    result = _run_flua("-l", "package", "-e", 'print("E_OK")', str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "E_OK" in result.stdout, result.stdout
    assert "SCRIPT_OK" in result.stdout, result.stdout


def test_debugger_vscode_extension_injected_bootstrap(tmp_path) -> None:
    """The alexeymelnichuk.lua-mobdebug launch flow, end to end.

    The extension prepends its own lua dir to package.path and starts its
    debugger client with `require'vscode-mobdebug'.start('127.0.0.1', PORT)`.
    flua must resolve that module name to its own mobdebug (the extension's
    bundled copy is incompatible with Lua 5.5) and still find its runtime
    libs for the script QA — the fake lua dir below is deliberately empty.
    """
    script = tmp_path / "ext_dbg.lua"
    script.write_text(
        'print("EXT_START")\n'
        "local x = 1\n"  # line 2 — breakpoint
        "local y = x + 1\n"
        'print("EXT_END", y)\n'
        "exit(0)\n"
    )
    base = str(tmp_path.resolve())
    script_path = str(script.resolve())

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    events: list[str] = []
    top_frame: dict = {}

    def fake_adapter() -> None:
        listener.settimeout(20)
        try:
            conn, _ = listener.accept()
        except TimeoutError:
            return
        events.append("connected")
        try:
            conn.sendall(_vsc_frame({
                "command": "welcome",
                "arguments": {
                    "sourceBasePath": base,
                    "stopOnEntry": False,
                    "directorySeperator": "/",
                    "pathMap": [],
                },
            }))
            time.sleep(0.3)
            conn.sendall(_vsc_frame({
                "seq": 1,
                "type": "request",
                "command": "setBreakpoints",
                "arguments": {
                    "source": {"path": script_path},
                    "breakpoints": [{"line": 2}],
                },
            }))
            time.sleep(0.2)
            conn.sendall(_vsc_frame({
                "seq": 2, "type": "request", "command": "configurationDone",
            }))
            conn.settimeout(15.0)
            while True:
                msg = _vsc_read(conn)
                if msg is None:
                    break
                if msg.get("type") == "event" and msg.get("event") == "stopped":
                    events.append(f"stopped:{msg['body'].get('reason')}")
                    conn.sendall(_vsc_frame({
                        "seq": 3,
                        "type": "request",
                        "command": "stackTrace",
                        "arguments": {"threadId": 0, "startFrame": 0, "levels": 2},
                    }))
                    while True:
                        r = _vsc_read(conn)
                        if r is None:
                            break
                        if r.get("type") == "response" and r.get("request_seq") == 3:
                            frames = ((r.get("body") or {}).get("stackFrames") or [])
                            if frames:
                                top_frame["path"] = frames[0]["source"]["path"]
                                top_frame["line"] = frames[0]["line"]
                            break
                    conn.sendall(_vsc_frame({
                        "seq": 4, "type": "request", "command": "continue",
                    }))
                    break
        finally:
            conn.close()
            listener.close()

    thread = threading.Thread(target=fake_adapter, daemon=True)
    thread.start()
    # the extension's injected bootstrap; the prepended dir does not exist,
    # so any require that falls through to it would fail
    inject = (
        f"package.path='{base}/no-such-ext-lua/?.lua;'..package.path;"
        f"require'vscode-mobdebug'.start('127.0.0.1',{port})"
    )
    result = _run_flua("-l", "package", "-e", inject, str(script))
    thread.join(timeout=30)

    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert events and events[0] == "connected", f"debuggee never connected: {events}"
    assert "stopped:breakpoint" in events, f"no breakpoint stop: {events}"
    assert "EXT_END" in result.stdout, "program did not finish after resume"
    assert "Warning: mobdebug failed" not in result.stdout, result.stdout
    assert "error loading module" not in result.stdout, result.stdout
    assert top_frame.get("path", "").endswith("/ext_dbg.lua"), top_frame
    assert top_frame.get("line") == 2, top_frame
