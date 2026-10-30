"""net.WebSocketClient: RFC 6455 client against a minimal local echo server."""

import asyncio
import base64
import hashlib
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
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

    def __init__(
        self,
        tls_ctx: ssl.SSLContext | None = None,
        initial_frame: bytes | None = None,
        handshake_delay: float = 0.0,
    ) -> None:
        self.seen_requests: list[bytes] = []  # raw handshakes (for assertions)
        self.seen_frames: list[tuple[int, bytes]] = []  # frames from the client
        self.initial_frame = initial_frame  # sent with the 101 response (one segment)
        self.handshake_delay = handshake_delay  # slow 101 (close-before-connected)
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        if tls_ctx is not None:
            # wrap BEFORE the accept loop starts — a late wrap races the
            # already-blocked accept() with a plain-TCP connection
            self.listener = tls_ctx.wrap_socket(self.listener, server_side=True)
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.listener.accept()
            except (ssl.SSLError, ConnectionResetError):
                # a client aborted its TLS handshake (e.g. certificate
                # verification failed) — keep serving the others
                continue
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
            self.seen_requests.append(request)
            if self.handshake_delay:
                time.sleep(self.handshake_delay)
            accept = base64.b64encode(
                hashlib.sha1(match.group(1).strip() + _GUID).digest()
            ).decode()
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
            if self.initial_frame is not None:
                # same segment as the handshake — Home Assistant sends its
                # auth_required frame this way
                response += self.initial_frame
            conn.sendall(response)
            while True:
                frame = _read_frame(conn)
                if frame is None:
                    return
                opcode, payload = frame
                self.seen_frames.append((opcode, payload))
                if opcode == 0x8:  # close
                    conn.sendall(_server_frame(0x8, payload))
                    return
                if opcode == 0x9:  # ping -> pong
                    conn.sendall(_server_frame(0xA, payload))
                elif opcode in (0x1, 0x2):
                    conn.sendall(_server_frame(opcode, payload))


async def _run_qa(script: str, capsys, needle: str, timeout: float = 5.0) -> str:
    """Run a QA and wait until needle appears in its output (the accumulated
    output is returned — the caller owns capsys from here on)."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/qa.lua"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        engine = LuaEngine()
        await engine.start()
        try:
            engine.start_qa(path, None, {}, path)
            seen = ""
            deadline = time.monotonic() + timeout
            while needle not in seen:
                if time.monotonic() > deadline:
                    raise AssertionError(f"{needle!r} not seen; output so far:\n{seen}")
                await asyncio.sleep(0.01)
                seen += capsys.readouterr().out
            return seen
        finally:
            await engine.stop()


@pytest.mark.asyncio
async def test_websocket_binary_roundtrip(capsys) -> None:
    # the new HC3 binary mode: sendBinary sends a binary frame; dataReceived
    # gets the raw bytes with isBinary=true
    server = EchoWsServer()
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local ws = net.WebSocketClient()\n"
        "  ws:addEventListener('dataReceived', function(payload, isBinary)\n"
        "    local b = {}\n"
        "    for i = 1, #payload do b[#b + 1] = string.byte(payload, i) end\n"
        "    print('BIN', tostring(isBinary), #payload, table.concat(b, ','))\n"
        "    ws:close()\n"
        "  end)\n"
        "  ws:addEventListener('connected', function()\n"
        "    ws:sendBinary(string.char(0x10, 0x16, 0x00, 0xFF))\n"
        "  end)\n"
        "  ws:addEventListener('error', function(e) print('ERR', tostring(e)) end)\n"
        f"  ws:connect('ws://127.0.0.1:{server.port}/')\n"
        "end, 20)\n",
        capsys=capsys,
        needle="BIN true",
    )
    assert "BIN true 4 16,22,0,255" in out
    assert "ERR" not in out


@pytest.mark.asyncio
async def test_websocket_connect_headers(capsys) -> None:
    # the HC3 supports a headers table as the second connect() argument
    server = EchoWsServer()
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local ws = net.WebSocketClient()\n"
        "  ws:addEventListener('connected', function() print('CONNECTED'); ws:close() end)\n"
        "  ws:addEventListener('error', function(e) print('ERR', tostring(e)) end)\n"
        f"  ws:connect('ws://127.0.0.1:{server.port}/', "
        "{['Authorization'] = 'Basic abc123', ['X-Custom'] = 'yes'})\n"
        "end, 20)\n",
        capsys=capsys,
        needle="CONNECTED",
    )
    assert "CONNECTED" in out
    assert "ERR" not in out
    assert server.seen_requests
    assert b"Authorization: Basic abc123\r\n" in server.seen_requests[0]
    assert b"X-Custom: yes\r\n" in server.seen_requests[0]


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
        needle="CLOSED false",
    )
    assert "CONNECTED true" in out
    assert "DATA ping from flua" in out
    assert "CLOSED false" in out
    assert "ERROR" not in out


@pytest.mark.asyncio
async def test_websocket_frame_with_handshake_delivered_promptly(capsys) -> None:
    # Regression: a frame arriving in the same segment as the 101 response
    # (Home Assistant's auth_required) used to sit in the handshake buffer
    # until the next recv returned — so it surfaced only when the server
    # closed the socket 10s later. It must be delivered immediately, with no
    # further server traffic.
    server = EchoWsServer(initial_frame=_server_frame(0x1, b'{"type":"auth_required"}'))
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local ws = net.WebSocketClient({timeout = 2000})\n"
        "  ws:addEventListener('dataReceived', function(data)\n"
        "    print('DATA', data)\n"
        "    ws:close()\n"
        "  end)\n"
        "  ws:addEventListener('connected', function() print('CONNECTED') end)\n"
        "  ws:addEventListener('error', function(err) print('ERROR', err) end)\n"
        f"  ws:connect('ws://127.0.0.1:{server.port}/')\n"
        "end, 20)\n",
        capsys=capsys,
        needle="DATA",
        timeout=3.0,
    )
    assert 'DATA {"type":"auth_required"}' in out
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
        needle="ERROR true",
    )
    assert "ERROR true" in out
    assert "SHOULD_NOT_FIRE" not in out


def test_example_websocket_runs_cleanly() -> None:
    # The example targets wss://echo.websocket.org — network dependent, so
    # assert only the deterministic parts: clean exit, no traceback, and one
    # of the two outcome markers (connected+echo, or a reported error).
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/websocket.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stack traceback" not in result.stdout
    assert ("echo:" in result.stdout) or ("ws error:" in result.stdout)


@pytest.mark.asyncio
async def test_wss_self_signed_default_skips_verification(capsys) -> None:
    # the HC3's WebSocketClientTls does NOT verify certificates by default
    # (embedded bridges ship self-signed certs — e.g. Dirigera); the flua
    # extension {checkCertificate = true} opts back into verification
    import ssl as _ssl

    ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(
        str(Path(__file__).parent / "certs" / "cert.pem"),
        str(Path(__file__).parent / "certs" / "key.pem"),
    )
    server = EchoWsServer(tls_ctx=ctx)

    out = await _run_qa(
        "local gotEcho, gotStrict = false, false\n"
        "local ok = net.WebSocketClientTls()\n"
        "ok:addEventListener('connected', function() print('CONNECTED'); ok:send('hi') end)\n"
        "ok:addEventListener('dataReceived', function(d) print('ECHO', d); gotEcho = true end)\n"
        "ok:addEventListener('error', function(e) print('DEF_ERR', e) end)\n"
        f"ok:connect('wss://127.0.0.1:{server.port}', nil)\n"
        "local strict = net.WebSocketClientTls()\n"
        "strict:addEventListener('error', function(e)\n"
        "  print('STRICT_ERR', tostring(e):find('CERTIFICATE') ~= nil); gotStrict = true end)\n"
        f"strict:connect('wss://127.0.0.1:{server.port}', nil, {{checkCertificate = true}})\n"
        "local deadline = os.time() + 3\n"
        "local function poll()\n"
        "  if gotEcho and gotStrict then print('DONE') return end\n"
        "  if os.time() > deadline then print('TIMEOUT', gotEcho, gotStrict) return end\n"
        "  setTimeout(poll, 100)\n"
        "end\n"
        "setTimeout(poll, 100)\n",
        capsys,
        "DONE",
    )
    assert "CONNECTED" in out
    assert "ECHO hi" in out
    assert "DEF_ERR" not in out  # the default skipped verification
    assert "STRICT_ERR true" in out  # opting in verifies (and fails here)


@pytest.mark.asyncio
async def test_websocket_debug_trace_logs_frames(capsys) -> None:
    # --%%debug:ws=true: the byte-level story — the "buffered N bytes after
    # connect" line (the signal that exposed the 0.1.86 handshake bug),
    # rx/tx frame lines with secret-masked previews, and the close reason
    server = EchoWsServer(
        initial_frame=_server_frame(0x1, b'{"type":"auth_required","token":"s3cret"}')
    )
    engine = LuaEngine()
    engine.config = {"debug": {"ws": True}}
    await engine.start()
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/qa.lua"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "setTimeout(function()\n"
                    "  local ws = net.WebSocketClient({timeout = 2000})\n"
                    "  ws:addEventListener('dataReceived', function(data)\n"
                    "    print('DATA', data)\n"
                    "    ws:close()\n"
                    "  end)\n"
                    f"  ws:connect('ws://127.0.0.1:{server.port}/')\n"
                    "end, 20)\n"
                )
            engine.start_qa(path, None, {}, path)
            seen = ""
            deadline = time.monotonic() + 5
            while "DATA" not in seen:
                if time.monotonic() > deadline:
                    raise AssertionError(f"'DATA' not seen; output so far:\n{seen}")
                await asyncio.sleep(0.01)
                seen += capsys.readouterr().out
    finally:
        await engine.stop()
    assert "buffered" in seen and "bytes after connect" in seen
    assert "rx text" in seen  # the frame that rode the handshake segment
    # the trace preview masks credential-ish values (the QA's own dataReceived
    # event still gets the real payload — masking is a trace concern only)
    ws_lines = [line for line in seen.splitlines() if line.startswith("ws ")]
    assert any('"token":"***"' in line for line in ws_lines)
    assert not any("s3cret" in line for line in ws_lines)
    assert "tx close" in seen  # the QA's close handshake


@pytest.mark.asyncio
async def test_websocket_subprotocol_header_canonical_and_validated(capsys) -> None:
    # the HC3's Sec-WebSocket-Protocol handling: entries split on commas,
    # joined canonically (", "), and a non-HTTP-token entry is a connect
    # error delivered through the error event
    server = EchoWsServer()
    seen = await _run_qa(
        f"""
        local ws = net.WebSocketClient()
        ws:addEventListener("connected", function() print("CONNECTED") exit(0) end)
        ws:addEventListener("error", function(err) print("ERROR", err) exit(0) end)
        ws:connect("ws://127.0.0.1:{server.port}/", {{["Sec-WebSocket-Protocol"]="mqtt,  v1"}})
        """,
        capsys,
        "CONNECTED",
    )
    assert b"Sec-WebSocket-Protocol: mqtt, v1\r\n" in server.seen_requests[0]
    assert "ERROR" not in seen

    bad = EchoWsServer()
    seen = await _run_qa(
        f"""
        local ws = net.WebSocketClient()
        ws:addEventListener("error", function(err) print("ERROR", err) exit(0) end)
        ws:connect("ws://127.0.0.1:{bad.port}/", {{["Sec-WebSocket-Protocol"]="mq tt"}})
        """,
        capsys,
        "ERROR",
    )
    assert "invalid Sec-WebSocket-Protocol" in seen


@pytest.mark.asyncio
async def test_websocket_text_send_rejects_invalid_utf8(capsys) -> None:
    # RFC 6455: a text frame must be valid UTF-8 — invalid bytes fire the
    # error event (pointing at sendBinary) and nothing reaches the wire
    server = EchoWsServer()
    seen = await _run_qa(
        f"""
        local ws = net.WebSocketClient()
        ws:addEventListener("connected", function() ws:send(string.char(255)) end)
        ws:addEventListener("error", function(err) print("ERROR", err) exit(0) end)
        ws:connect("ws://127.0.0.1:{server.port}/")
        """,
        capsys,
        "ERROR",
    )
    assert "sendBinary" in seen
    await asyncio.sleep(0.3)  # give a hypothetical frame time to arrive
    assert all(opcode != 0x1 for opcode, _ in server.seen_frames)  # no text frame


@pytest.mark.asyncio
async def test_websocket_close_before_connected_fires_only_disconnected(capsys) -> None:
    # a close() while the handshake is in flight: connected is never
    # delivered, only disconnected once the socket is down (the HC3 contract)
    server = EchoWsServer(handshake_delay=0.5)
    seen = await _run_qa(
        f"""
        local ws = net.WebSocketClient()
        ws:addEventListener("connected", function() print("EVENT_CONNECTED") end)
        ws:addEventListener("disconnected", function() print("EVENT_DISCONNECTED") exit(0) end)
        ws:connect("ws://127.0.0.1:{server.port}/")
        ws:close()
        """,
        capsys,
        "EVENT_DISCONNECTED",
    )
    assert "EVENT_CONNECTED" not in seen, seen


class MqttBrokerWs(EchoWsServer):
    """Speaks just enough MQTT 3.1.1 over the websocket echo server:
    CONNACK on CONNECT, SUBACK on SUBSCRIBE, close on DISCONNECT."""

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
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
            conn.sendall(response)
            while True:
                frame = _read_frame(conn)
                if frame is None:
                    return
                opcode, payload = frame
                if opcode == 0x8:
                    conn.sendall(_server_frame(0x8, payload))
                    return
                if opcode != 0x2 or not payload:
                    continue
                kind = payload[0] >> 4
                if kind == 0x1:  # CONNECT -> CONNACK (session present)
                    conn.sendall(_server_frame(0x2, bytes([0x20, 0x02, 0x00, 0x00])))
                elif kind == 0x8:  # SUBSCRIBE -> SUBACK (granted QoS 0)
                    conn.sendall(_server_frame(0x2, bytes([0x90, 0x03]) + payload[2:4] + b"\x00"))
                elif kind == 0xE:  # DISCONNECT -> done
                    return


def test_example_mqtt_over_websocket_runs_against_a_mock_broker() -> None:
    # the 5.221 pattern: MQTT built in Lua on top of the websocket client —
    # the example's CONNECT/SUBSCRIBE/DISCONNECT flow completes against a
    # minimal broker, byte-for-byte
    broker = MqttBrokerWs()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flua",
            "--nogreet",
            "-D",
            f'var:BROKER_URL="ws://127.0.0.1:{broker.port}/mqtt"',
            "examples/mqtt-over-websocket.lua",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CONNACK received" in result.stdout
    assert "SUBACK received" in result.stdout


def test_example_mqtt_over_websocket_terminates_without_a_broker() -> None:
    # the example's error path: connection refused -> error event -> clean exit
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flua",
            "--nogreet",
            "-D",
            'var:BROKER_URL="ws://127.0.0.1:1/mqtt"',
            "examples/mqtt-over-websocket.lua",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ws error" in result.stdout
