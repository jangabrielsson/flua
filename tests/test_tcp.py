"""net.TCPSocket: the documented HC3 callback API over the worker-thread bridge."""

import asyncio
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine

REPO_ROOT = Path(__file__).resolve().parent.parent


def _echo_server() -> tuple[threading.Thread, int]:
    """Threaded echo server on an ephemeral port."""

    def serve() -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        ports.append(listener.getsockname()[1])
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            threading.Thread(target=echo_loop, args=(conn,), daemon=True).start()

    def echo_loop(conn: socket.socket) -> None:
        with conn:
            while True:
                data = conn.recv(4096)
                if not data:
                    return
                conn.sendall(data)

    ports: list[int] = []
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    while not ports:
        time.sleep(0.01)
    return thread, ports[0]


def _silent_server() -> int:
    """Accepts a connection and never sends anything (for read timeouts)."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def hold() -> None:
        try:
            conn, _ = listener.accept()
            time.sleep(3.0)  # hold without replying
            conn.close()
        except OSError:
            pass

    threading.Thread(target=hold, daemon=True).start()
    return port


async def _run_qa(script: str, sleep: float = 0.8, capsys=None) -> str:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/qa.lua"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        engine = LuaEngine()
        await engine.start()
        try:
            engine.start_qa(path, None, {}, path)
            await asyncio.sleep(sleep)
        finally:
            await engine.stop()
    return capsys.readouterr().out


@pytest.mark.asyncio
async def test_tcp_echo_roundtrip(capsys) -> None:
    _, port = _echo_server()
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local sock = net.TCPSocket({timeout = 2000})\n"
        f"  sock:connect('127.0.0.1', {port}, {{\n"
        "    success = function()\n"
        "      print('CONNECTED')\n"
        "      sock:send('ping from flua\\n', {\n"
        "        success = function()\n"
        "          sock:readUntil('\\n', {\n"
        "            success = function(data)\n"
        "              print('READ', data)\n"
        "              sock:close()\n"
        "            end,\n"
        "            error = function(e) print('READ ERR', e) end,\n"
        "          })\n"
        "        end,\n"
        "        error = function(e) print('SEND ERR', e) end,\n"
        "      })\n"
        "    end,\n"
        "    error = function(e) print('CONNECT ERR', e) end,\n"
        "  })\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "CONNECTED" in out
    assert "READ ping from flua" in out
    assert "ERR" not in out


@pytest.mark.asyncio
async def test_tcp_connect_refused(capsys) -> None:
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local sock = net.TCPSocket({timeout = 1000})\n"
        "  sock:connect('127.0.0.1', 1, {\n"
        "    success = function() print('SHOULD_NOT_FIRE') end,\n"
        "    error = function(e) print('REFUSED', e ~= nil) end,\n"
        "  })\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "REFUSED true" in out
    assert "SHOULD_NOT_FIRE" not in out


@pytest.mark.asyncio
async def test_tcp_read_timeout(capsys) -> None:
    port = _silent_server()
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local sock = net.TCPSocket({timeout = 150})\n"
        f"  sock:connect('127.0.0.1', {port}, {{\n"
        "    success = function()\n"
        "      sock:read({\n"
        "        success = function(d) print('GOT', d) end,\n"
        "        error = function(e) print('TIMEOUT', e) end,\n"
        "      })\n"
        "    end,\n"
        "    error = function(e) print('CONNECT ERR', e) end,\n"
        "  })\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "TIMEOUT timeout" in out
    assert "GOT" not in out


def test_example_tcp_runs_cleanly() -> None:
    # No echo service on 7777 in CI: the example must exit 0 and print its
    # instructions. Either marker proves the script ran without errors.
    result = subprocess.run(
        [sys.executable, "-m", "flua", "examples/tcp.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stack traceback" not in result.stdout
    assert ("connect failed:" in result.stdout) or ("echo:" in result.stdout)
