"""mqtt.* client: MQTT 3.1.1 against a minimal local broker."""

import asyncio
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


def _encode_remaining_length(n: int) -> bytes:
    out = bytearray()
    while True:
        digit = n % 128
        n //= 128
        if n:
            digit |= 0x80
        out.append(digit)
        if not n:
            return bytes(out)


def _read_packet(conn: socket.socket) -> tuple[int, bytes] | None:
    header = b""
    while len(header) < 1:
        chunk = conn.recv(1)
        if not chunk:
            return None
        header += chunk
    remaining = 0
    multiplier = 1
    while True:
        digit = conn.recv(1)
        if not digit:
            return None
        remaining += (digit[0] & 0x7F) * multiplier
        if not digit[0] & 0x80:
            break
        multiplier *= 128
    body = b""
    while len(body) < remaining:
        body += conn.recv(remaining - len(body))
    return header[0], body


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    length = struct.unpack(">H", data[offset : offset + 2])[0]
    offset += 2
    return data[offset : offset + length].decode("utf-8", errors="replace"), offset + length


def _packet(header: int, body: bytes = b"") -> bytes:
    return bytes([header]) + _encode_remaining_length(len(body)) + body


def _topic_matches(pattern: str, topic: str) -> bool:
    if pattern == "#":
        return True
    if pattern == topic:
        return True
    if pattern.endswith("/#"):
        return topic.startswith(pattern[:-1])
    return False


class MiniBroker:
    """Minimal MQTT 3.1.1 broker: CONNECT/SUBSCRIBE/PUBLISH echo/PING/DISCONNECT."""

    def __init__(self) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        self.port = self.listener.getsockname()[1]
        self._clients: list[socket.socket] = []
        self._subs: list[tuple[socket.socket, str, int]] = []  # (conn, topic, qos)
        self._lock = threading.Lock()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            with self._lock:
                self._clients.append(conn)
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            while True:
                packet = _read_packet(conn)
                if packet is None:
                    break
                header, body = packet
                ptype = header >> 4
                if ptype == 1:  # CONNECT
                    conn.sendall(_packet(0x20, b"\x00\x00"))  # CONNACK: session 0, accepted
                elif ptype == 8:  # SUBSCRIBE
                    packet_id = struct.unpack(">H", body[:2])[0]
                    offset = 2
                    granted = []
                    while offset < len(body):
                        topic, offset = _read_string(body, offset)
                        qos = body[offset]
                        offset += 1
                        granted.append(qos)
                        with self._lock:
                            self._subs.append((conn, topic, qos))
                    conn.sendall(_packet(0x90, struct.pack(">H", packet_id) + bytes(granted)))
                elif ptype == 10:  # UNSUBSCRIBE
                    packet_id = struct.unpack(">H", body[:2])[0]
                    offset = 2
                    while offset < len(body):
                        topic, offset = _read_string(body, offset)
                        with self._lock:
                            self._subs = [
                                (c, t, q)
                                for c, t, q in self._subs
                                if not (c is conn and t == topic)
                            ]
                    conn.sendall(_packet(0xB0, struct.pack(">H", packet_id)))
                elif ptype == 3:  # PUBLISH
                    self._handle_publish(conn, header, body)
                elif ptype == 12:  # PINGREQ
                    conn.sendall(_packet(0xD0))
                elif ptype == 14:  # DISCONNECT
                    break

    def _handle_publish(self, sender: socket.socket, header: int, body: bytes) -> None:
        topic, offset = _read_string(body, 0)
        qos = (header >> 1) & 0x03
        packet_id = None
        if qos > 0:
            packet_id = struct.unpack(">H", body[offset : offset + 2])[0]
            offset += 2
        payload = body[offset:]
        with self._lock:
            subs = [(c, t) for c, t, _ in self._subs if _topic_matches(t, topic)]
        for target, _ in subs:
            try:
                forward = 0x30 | (0x01 if header & 0x01 else 0) | (0x02 if qos > 0 else 0)
                body_bytes = _encode_string_bytes(topic)
                if qos > 0:
                    body_bytes += struct.pack(">H", 1)  # fresh packet id for the forward
                body_bytes += payload
                target.sendall(_packet(forward, body_bytes))
            except OSError:
                pass
        if qos == 1:
            sender.sendall(_packet(0x40, struct.pack(">H", packet_id)))


def _encode_string_bytes(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


async def _run_qa(script: str, sleep: float = 1.2, capsys=None) -> str:
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
async def test_mqtt_connect_subscribe_publish_roundtrip(capsys) -> None:
    broker = MiniBroker()
    out = await _run_qa(
        "setTimeout(function()\n"
        f"  local client = mqtt.Client.connect('mqtt://127.0.0.1:{broker.port}', {{\n"
        "    clientId = 'flua-test',\n"
        "    callback = function(code) print('CONNECT CB', code) end,\n"
        "  })\n"
        "  client:addEventListener('connected', function(e)\n"
        "    print('CONNECTED', e.sessionPresent, e.returnCode, client:isConnected())\n"
        "    local pid = client:subscribe('flua/test', { qos = mqtt.QoS.AT_LEAST_ONCE, "
        "callback = function(c) print('SUB CB', c) end })\n"
        "    print('SUB PID', type(pid) == 'number')\n"
        "  end)\n"
        "  client:addEventListener('subscribed', function(e)\n"
        "    print('SUBSCRIBED', e.packetId ~= nil, e.results[1])\n"
        "    client:publish('flua/test', 'hello', { qos = 1, retain = true, "
        "callback = function(c) print('PUB CB', c) end })\n"
        "  end)\n"
        "  client:addEventListener('published', function(e)\n"
        "    print('PUBLISHED', e.packetId ~= nil)\n"
        "  end)\n"
        "  client:addEventListener('message', function(e)\n"
        "    print('MESSAGE', e.topic, e.payload, e.qos, e.retain)\n"
        "  end)\n"
        "  client:addEventListener('error', function(e) print('ERROR', e.code) end)\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "CONNECT CB 0" in out
    assert "CONNECTED false 0 true" in out
    assert "SUB PID true" in out
    assert "SUB CB 0" in out
    assert "SUBSCRIBED true 1" in out
    assert "PUBLISHED true" in out
    assert "MESSAGE flua/test hello 1 true" in out
    assert "ERROR" not in out


@pytest.mark.asyncio
async def test_mqtt_connect_refused(capsys) -> None:
    out = await _run_qa(
        "setTimeout(function()\n"
        "  local client = mqtt.Client.connect('mqtt://127.0.0.1:1', {\n"
        "    callback = function(code) print('CONNECT CB', code) end,\n"
        "  })\n"
        "  client:addEventListener('connected', function() print('SHOULD_NOT_FIRE') end)\n"
        "  client:addEventListener('error', function(e) print('ERR') end)\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "CONNECT CB -1" in out
    assert "SHOULD_NOT_FIRE" not in out


@pytest.mark.asyncio
async def test_mqtt_unsubscribe(capsys) -> None:
    broker = MiniBroker()
    out = await _run_qa(
        "setTimeout(function()\n"
        f"  local client = mqtt.Client.connect('mqtt://127.0.0.1:{broker.port}')\n"
        "  client:addEventListener('connected', function()\n"
        "    client:subscribe('flua/x')\n"
        "  end)\n"
        "  client:addEventListener('subscribed', function()\n"
        "    client:unsubscribe('flua/x')\n"
        "  end)\n"
        "  client:addEventListener('unsubscribed', function(e)\n"
        "    print('UNSUBSCRIBED', e.packetId ~= nil)\n"
        "  end)\n"
        "  client:addEventListener('error', function(e) print('ERROR', e.code) end)\n"
        "end, 20)\n",
        capsys=capsys,
    )
    assert "UNSUBSCRIBED true" in out
    assert "ERROR" not in out


def test_example_mqtt_runs_cleanly() -> None:
    # The example targets the public broker broker.hivemq.com — network
    # dependent, so assert only the deterministic parts: clean exit, no
    # traceback, and one of the two outcome markers.
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/mqtt.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stack traceback" not in result.stdout
    assert ("mqtt echo:" in result.stdout) or ("mqtt error" in result.stdout)
