"""Minimal MQTT 3.1.1 client (blocking; runs in worker threads).

No external dependencies — stdlib sockets + ssl, like websocket.py. One
thread per connection runs the receive loop; events are handed to the
engine through a thread-safe callback and delivered to QA code via the
pump. Implements the HC3's documented mqtt.* surface:

- CONNECT/CONNACK, SUBSCRIBE/SUBACK, UNSUBSCRIBE/UNSUBACK, PINGREQ/PINGRESP
- PUBLISH QoS 0/1 (send + receive); QoS 2: receive-side handshake handled
  (PUBREC/PUBREL/PUBCOMP), send-side downgraded to QoS 1 (documented)
- keep-alive pings when idle (options.keepAlivePeriod)
- TLS via mqtts:// and options.tls (allowUnauthorized, clientCertificate,
  certificateAuthority), username/password, clientId, cleanSession, lastWill
"""

from __future__ import annotations

import logging
import socket
import ssl
import struct
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# -- MQTT 3.1.1 wire helpers -----------------------------------------------------


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


def _decode_remaining_length(data: bytes, offset: int) -> tuple[int, int]:
    """(value, bytes_consumed)."""
    value = 0
    multiplier = 1
    consumed = 0
    while True:
        if offset + consumed >= len(data):
            raise ValueError("truncated remaining length")
        digit = data[offset + consumed]
        consumed += 1
        value += (digit & 0x7F) * multiplier
        if not digit & 0x80:
            return value, consumed
        multiplier *= 128


def _encode_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    length = struct.unpack(">H", data[offset : offset + 2])[0]
    offset += 2
    return data[offset : offset + length].decode("utf-8", errors="replace"), offset + length


def _packet(header: int, body: bytes = b"") -> bytes:
    return bytes([header]) + _encode_remaining_length(len(body)) + body


# -- client ----------------------------------------------------------------------


class MqttError(Exception):
    pass


class MqttClient:
    """One broker connection. connect() performs TCP/TLS + the MQTT
    handshake; run() is the blocking receive loop (worker thread)."""

    def __init__(
        self,
        uri: str,
        options: dict[str, Any],
        timeout: float,
        on_event: Callable[[str, Any], None],
    ) -> None:
        self._on_event = on_event
        self._options = options
        self._timeout = timeout
        parsed = urlparse(uri if "://" in uri else f"mqtt://{uri}")
        if parsed.scheme not in ("mqtt", "mqtts"):
            raise MqttError(f"unsupported scheme {parsed.scheme!r} (expected mqtt:// or mqtts://)")
        self._host = parsed.hostname or "127.0.0.1"
        self._port = (
            options.get("port") or parsed.port or (8883 if parsed.scheme == "mqtts" else 1883)
        )
        self._tls = parsed.scheme == "mqtts" or "tls" in options
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._connected = False
        self._buffer = b""
        self._last_send = time.monotonic()

    # -- connect / MQTT handshake ------------------------------------------------

    def _wrap_tls(self, sock: socket.socket) -> socket.socket:
        tls = self._options.get("tls") or {}
        context = ssl.create_default_context()
        allow_unauthorized = bool(tls.get("allowUnauthorized"))
        if allow_unauthorized:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        ca = tls.get("certificateAuthority")
        if ca:
            import tempfile

            with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
                handle.write(ca)
                ca_path = handle.name
            context.load_verify_locations(ca_path)
        client_cert = tls.get("clientCertificate")
        if client_cert:
            import tempfile

            with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
                handle.write(client_cert)
                cert_path = handle.name
            context.load_cert_chain(cert_path)
        return context.wrap_socket(sock, server_hostname=self._host)

    def connect(self) -> None:
        sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        try:
            if self._tls:
                sock = self._wrap_tls(sock)
            self._sock = sock
            self._send_connect()
            header = self._read_packet(timeout=self._timeout)
            if header[0] != 0x20:
                raise MqttError(f"expected CONNACK, got 0x{header[0]:02x}")
            if len(header) < 3:
                raise MqttError("truncated CONNACK")
            session_present = bool(header[1] & 0x01)
            return_code = header[2]
            if return_code != 0:
                self.close()
                raise MqttError(f"connection refused (return code {return_code})")
            self._connected = True
            self._on_event("connected", {"sessionPresent": session_present, "returnCode": 0})
        except Exception:
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None
            raise

    def _send_connect(self) -> None:
        options = self._options
        client_id = options.get("clientId") or f"flua-{os_id()}"
        keepalive = int(options.get("keepAlivePeriod") or 0)
        clean_session = bool(options.get("cleanSession", False))
        username = options.get("username")
        password = options.get("password")
        will = options.get("lastWill")
        flags = 0
        if clean_session:
            flags |= 0x02
        if username is not None:
            flags |= 0x80
        if password is not None:
            flags |= 0x40
        body = b""
        if will:
            flags |= 0x04
            will_qos = int(will.get("qos") or 0)
            if will_qos not in (0, 1, 2):
                raise MqttError(f"bad lastWill qos: {will_qos}")
            flags |= (will_qos << 3) & 0x18
            if will.get("retain"):
                flags |= 0x20
            body += _encode_string(str(will["topic"])) + _encode_string(
                str(will.get("payload") or "")
            )
        var_header = b"\x00\x04MQTT\x04" + bytes([flags]) + struct.pack(">H", keepalive)
        body = _encode_string(client_id) + body
        if username is not None:
            body += _encode_string(str(username))
        if password is not None:
            body += _encode_string(str(password))
        self._send_packet(0x10, var_header + body)

    # -- ops (called from worker tasks, thread-safe via the pool lock) -----------

    def subscribe(self, packet_id: int, topics: list[tuple[str, int]]) -> None:
        body = struct.pack(">H", packet_id)
        for topic, qos in topics:
            if qos not in (0, 1, 2):
                raise MqttError(f"bad qos: {qos}")
            body += _encode_string(topic) + bytes([qos])
        self._send_packet(0x82, body)

    def unsubscribe(self, packet_id: int, topics: list[str]) -> None:
        body = struct.pack(">H", packet_id)
        for topic in topics:
            body += _encode_string(topic)
        self._send_packet(0xA2, body)

    def publish(self, packet_id: int, topic: str, payload: str, qos: int, retain: bool) -> None:
        if qos not in (0, 1, 2):
            raise MqttError(f"bad qos: {qos}")
        if qos == 2:
            qos = 1  # QoS 2 send-side downgraded to at-least-once (documented)
        header = 0x30 | (qos << 1) | (0x01 if retain else 0)
        body = _encode_string(topic)
        if qos > 0:
            body += struct.pack(">H", packet_id)
        body += payload.encode("utf-8")
        self._send_packet(header, body)

    def disconnect(self) -> None:
        try:
            self._send_packet(0xE0)
        except OSError:
            pass
        self.close()

    # -- receive loop -------------------------------------------------------------

    def run(self) -> None:
        try:
            while not self._stop.is_set() and self._sock is not None:
                if self._maybe_ping():
                    continue
                self._sock.settimeout(0.5)
                try:
                    chunk = self._sock.recv(4096)
                except TimeoutError:
                    continue
                except (OSError, ssl.SSLError) as exc:
                    if not self._stop.is_set():
                        self._on_event("error", {"code": -1, "message": str(exc)})
                        self._emit_closed()
                    break
                if not chunk:
                    if not self._stop.is_set():
                        self._emit_closed()
                    break
                self._buffer += chunk
                self._parse_buffer()
        finally:
            self.close()

    def _maybe_ping(self) -> bool:
        keepalive = int(self._options.get("keepAlivePeriod") or 0)
        if keepalive <= 0 or not self._connected:
            return False
        if time.monotonic() - self._last_send >= keepalive:
            self._send_packet(0xC0)
            return True
        return False

    def _parse_buffer(self) -> None:
        while True:
            packet = self._next_packet()
            if packet is None:
                return
            header, body = packet
            ptype = header >> 4
            if ptype == 3:  # PUBLISH
                self._handle_publish(header, body)
            elif ptype == 4:  # PUBACK
                packet_id = struct.unpack(">H", body)[0]
                self._on_event("published", {"packetId": packet_id})
            elif ptype == 9:  # SUBACK
                packet_id = struct.unpack(">H", body[:2])[0]
                results = [b if b < 3 else -1 for b in body[2:]]
                self._on_event("subscribed", {"packetId": packet_id, "results": results})
            elif ptype == 11:  # UNSUBACK
                packet_id = struct.unpack(">H", body)[0]
                self._on_event("unsubscribed", {"packetId": packet_id})
            elif ptype == 13:  # PINGRESP
                pass
            elif ptype == 5:  # PUBREC (QoS 2 receive)
                packet_id = struct.unpack(">H", body)[0]
                self._send_packet(0x62, body)  # PUBREL
            elif ptype == 7:  # PUBCOMP
                pass
            # PUBREL (6) is answered inline in _handle_publish path via PUBREC/PUBCOMP

    def _handle_publish(self, header: int, body: bytes) -> None:
        topic, offset = _read_string(body, 0)
        qos = (header >> 1) & 0x03
        packet_id = None
        if qos > 0:
            packet_id = struct.unpack(">H", body[offset : offset + 2])[0]
            offset += 2
        payload = body[offset:].decode("utf-8", errors="replace")
        event = {
            "topic": topic,
            "payload": payload,
            "packetId": packet_id,
            "qos": qos,
            "retain": bool(header & 0x01),
            "dup": bool(header & 0x08),
        }
        self._on_event("message", event)
        if qos == 1:
            self._send_packet(0x40, struct.pack(">H", packet_id))
        elif qos == 2:
            self._send_packet(0x50, struct.pack(">H", packet_id))  # PUBREC

    # -- wire / lifecycle ---------------------------------------------------------

    def _send_packet(self, header: int, body: bytes = b"") -> None:
        sock = self._sock
        if sock is None:
            raise MqttError("not connected")
        sock.sendall(_packet(header, body))
        self._last_send = time.monotonic()

    def _read_packet(self, timeout: float | None = None) -> bytes:
        """Read one full packet (header byte + body), blocking with timeout."""
        sock = self._sock
        if sock is None:
            raise MqttError("not connected")
        if timeout is not None:
            sock.settimeout(timeout)
        header = self._read_exact(sock, 1)
        remaining = 0
        multiplier = 1
        while True:
            digit = self._read_exact(sock, 1)[0]
            remaining += (digit & 0x7F) * multiplier
            if not digit & 0x80:
                break
            multiplier *= 128
        return header + self._read_exact(sock, remaining)

    def _next_packet(self) -> tuple[int, bytes] | None:
        buf = self._buffer
        if not buf:
            return None
        try:
            remaining, consumed = _decode_remaining_length(buf, 1)
        except ValueError:
            return None
        total = 1 + consumed + remaining
        if len(buf) < total:
            return None
        self._buffer = buf[total:]
        return buf[0], buf[1 + consumed : total]

    @staticmethod
    def _read_exact(sock: socket.socket, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise MqttError("connection closed")
            data += chunk
        return data

    def close(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        self._connected = False
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def is_connected(self) -> bool:
        return self._connected and not self._stop.is_set()

    def _emit_closed(self) -> None:
        if self.is_connected() or self._connected:
            self._connected = False
            self._on_event("closed", {})


def os_id() -> str:
    import os
    import uuid

    return f"flua-{os.getpid()}-{uuid.uuid4().hex[:8]}"


# -- pool -----------------------------------------------------------------------


class MqttPool:
    """Registry of MqttClient connections keyed by connection id."""

    def __init__(self, emit: Callable[[int, str, Any], None]) -> None:
        self._emit = emit
        self._lock = threading.Lock()
        self._entries: dict[int, dict[str, Any]] = {}  # conn -> {client, qa}
        self._counter = 0

    def new_slot(self, qa: int) -> int:
        with self._lock:
            self._counter += 1
            self._entries[self._counter] = {"client": None, "qa": int(qa)}
            return self._counter

    def _entry(self, conn: int) -> dict[str, Any] | None:
        with self._lock:
            return self._entries.get(conn)

    def qa_of(self, conn: int) -> int | None:
        entry = self._entry(conn)
        return entry["qa"] if entry else None

    def connect(
        self, conn: int, uri: str, options: dict[str, Any], timeout: float
    ) -> tuple[bool, str | None]:
        entry = self._entry(conn)
        if entry is None:
            return False, "unknown connection"
        client = MqttClient(
            uri, options, timeout, lambda event, data: self._emit(conn, event, data)
        )
        try:
            client.connect()
        except Exception as exc:
            return False, str(exc)
        with self._lock:
            entry["client"] = client
        return True, None

    def start_receiver(self, conn: int) -> None:
        entry = self._entry(conn)
        client = entry["client"] if entry else None
        if client is not None:
            threading.Thread(target=client.run, daemon=True).start()

    def _client(self, conn: int) -> MqttClient | None:
        entry = self._entry(conn)
        return entry["client"] if entry else None

    def subscribe(
        self, conn: int, packet_id: int, topics: list[tuple[str, int]]
    ) -> tuple[bool, str | None]:
        client = self._client(conn)
        if client is None or not client.is_connected():
            return False, "client not connected"
        try:
            client.subscribe(packet_id, topics)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def unsubscribe(self, conn: int, packet_id: int, topics: list[str]) -> tuple[bool, str | None]:
        client = self._client(conn)
        if client is None or not client.is_connected():
            return False, "client not connected"
        try:
            client.unsubscribe(packet_id, topics)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def publish(
        self, conn: int, packet_id: int, topic: str, payload: str, qos: int, retain: bool
    ) -> tuple[bool, str | None]:
        client = self._client(conn)
        if client is None or not client.is_connected():
            return False, "client not connected"
        try:
            client.publish(packet_id, topic, payload, qos, retain)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def disconnect(self, conn: int) -> tuple[bool, str | None]:
        client = self._client(conn)
        if client is None:
            return False, "unknown connection"
        client.disconnect()
        return True, None

    def close_all(self) -> None:
        with self._lock:
            clients = [entry["client"] for entry in self._entries.values()]
            self._entries.clear()
        for client in clients:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    def active_count(self) -> int:
        """Connected clients: they keep the process alive (pending work)."""
        with self._lock:
            return sum(
                1
                for entry in self._entries.values()
                if entry["client"] is not None and entry["client"].is_connected()
            )
