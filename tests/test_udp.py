"""net.UDPSocket: the documented HC3 callback API over the worker-thread bridge."""

import asyncio
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine

REPO_ROOT = Path(__file__).resolve().parent.parent


def _udp_echo_server() -> int:
    """Threaded UDP echo server on an ephemeral port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    def serve() -> None:
        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except OSError:
                return
            sock.sendto(data, addr)

    threading.Thread(target=serve, daemon=True).start()
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
async def test_udp_echo_roundtrip(capsys) -> None:
    port = _udp_echo_server()
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local udp = net.UDPSocket({timeout = 2000})\n"
        f"  udp:sendTo('ping', '127.0.0.1', {port}, {{\n"
        "    success = function()\n"
        "      print('SENT')\n"
        "      udp:receive({\n"
        "        success = function(data)\n"
        "          print('DATA', data)\n"
        "          udp:close()\n"
        "        end,\n"
        "        error = function(e) print('RECV ERR', e) end,\n"
        "      })\n"
        "    end,\n"
        "    error = function(e) print('SEND ERR', e) end,\n"
        "  })\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "SENT" in out
    assert "DATA ping" in out
    assert "ERR" not in out


@pytest.mark.asyncio
async def test_udp_receive_timeout(capsys) -> None:
    # no peer replies: receive must hit the options.timeout and call error
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local udp = net.UDPSocket({timeout = 150})\n"
        "  udp:receive({\n"
        "    success = function(d) print('GOT', d) end,\n"
        "    error = function(e) print('TIMEOUT', e) end,\n"
        "  })\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "TIMEOUT timeout" in out
    assert "GOT" not in out


def test_example_udp_runs_cleanly() -> None:
    # broadcast send succeeds without a listener; the receive then times out
    # cleanly — fully deterministic offline.
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/udp.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sent broadcast" in result.stdout
    assert "stack traceback" not in result.stdout
