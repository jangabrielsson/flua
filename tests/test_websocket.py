"""net.WebSocketClient: RFC 6455 client against a minimal local echo server."""

import asyncio
import base64
import hashlib
import re
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine

REPO_ROOT = Path(__file__).resolve().parent.parent

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _server_frame(opcode: int, payload: bytes) -> bytes:
    header = bytearray([0x80 | opcode])
    if len(payload) < 126:
        header.append(len(payload))
    elif len(payload) < 65536:
        header.append(126)
        header += struct.pack(">H", len(payload))
    else:
        header.append(127)
        header += struct.pack(">Q", len(payload))
    return bytes(header) + payload


def _read_frame(conn: socket.socket) -> tuple[int, bytes] | None:
    """Read one (masked) client frame."""
    header = b""
    while len(header) < 2:
        chunk = conn.recv(2 - len(header))
        if not chunk:
            return None
        header += chunk
    b0, b1 = header[0], header[1]
    opcode = b0 & 0x0F
    length = b1 & 0x7F
    extra = 0
    if length == 126:
        extra = 2
    elif length == 127:
        extra = 8
    rest = b""
    while len(rest) < extra:
        rest += conn.recv(extra - len(rest))
    if extra == 2:
        length = struct.unpack(">H", rest)[0]
    elif extra == 8:
        length = struct.unpack(">Q", rest)[0]
    mask = b""
    while len(mask) < 4:
        mask += conn.recv(4 - len(mask))
    payload = b""
    while len(payload) < length:
        payload += conn.recv(length - len(payload))
    unmasked = bytearray(payload)
    for i in range(len(unmasked)):
        unmasked[i] ^= mask[i % 4]
    return opcode, bytes(unmasked)


class EchoWsServer:
    """Minimal RFC 6455 server: accepts, handshakes, echoes text frames."""

    def __init__(self) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                request += chunk
            match = re.search(rb"Sec-WebSocket-Key: (.+)\r\n", request)
            if match is None:
                return
            accept = base64.b64encode(
                hashlib.sha1(match.group(1).strip() + _GUID).digest()
            ).decode()
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode()
            )
            while True:
                frame = _read_frame(conn)
                if frame is None:
                    return
                opcode, payload = frame
                if opcode == 0x8:  # close
                    conn.sendall(_server_frame(0x8, payload))
                    return
                if opcode == 0x9:  # ping -> pong
                    conn.sendall(_server_frame(0xA, payload))
                elif opcode in (0x1, 0x2):
                    conn.sendall(_server_frame(opcode, payload))


async def _run_qa(script: str, sleep: float = 1.0, capsys=None) -> str:
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
async def test_websocket_echo_roundtrip(capsys) -> None:
    server = EchoWsServer()
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local ws = net.WebSocketClient({timeout = 2000})\n"
        "  ws:addEventListener('connected', function()\n"
        "    print('CONNECTED', ws:isOpen())\n"
        "    ws:send('ping from flua')\n"
        "  end)\n"
        "  ws:addEventListener('dataReceived', function(data)\n"
        "    print('DATA', data)\n"
        "    ws:close()\n"
        "  end)\n"
        "  ws:addEventListener('disconnected', function()\n"
        "    print('CLOSED', ws:isOpen())\n"
        "  end)\n"
        "  ws:addEventListener('error', function(err) print('ERROR', err) end)\n"
        f"  ws:connect('ws://127.0.0.1:{server.port}/echo')\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "CONNECTED true" in out
    assert "DATA ping from flua" in out
    assert "CLOSED false" in out
    assert "ERROR" not in out


@pytest.mark.asyncio
async def test_websocket_connect_refused(capsys) -> None:
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local ws = net.WebSocketClient({timeout = 1000})\n"
        "  ws:addEventListener('connected', function() print('SHOULD_NOT_FIRE') end)\n"
        "  ws:addEventListener('error', function(err) print('ERROR', err ~= nil) end)\n"
        "  ws:connect('ws://127.0.0.1:1/')\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "ERROR true" in out
    assert "SHOULD_NOT_FIRE" not in out


def test_example_websocket_runs_cleanly() -> None:
    # The example targets wss://echo.websocket.org — network dependent, so
    # assert only the deterministic parts: clean exit, no traceback, and one
    # of the two outcome markers (connected+echo, or a reported error).
    result = subprocess.run(
        [sys.executable, "-m", "flua", "examples/websocket.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stack traceback" not in result.stdout
    assert ("echo:" in result.stdout) or ("ws error:" in result.stdout)
