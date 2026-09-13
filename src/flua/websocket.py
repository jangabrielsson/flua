"""Minimal RFC 6455 WebSocket client (blocking; runs in worker threads).

No external dependencies — stdlib sockets + ssl, keeping lupa the only
runtime requirement. One thread per connection runs the receive loop;
events (connected/disconnected/error/dataReceived) are handed to the
engine through a thread-safe callback and delivered to QA code via the
pump, like the other net.* classes.

Data fidelity: sends are UTF-8 text frames. Text frames arrive decoded as
UTF-8; binary frames arrive decoded as latin-1 (every byte preserved as a
character 0-255), since Lua strings are byte strings and the bridge is
UTF-8-strict.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import socket
import ssl
import struct
import threading
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_OP_CONT, _OP_TEXT, _OP_BINARY, _OP_CLOSE, _OP_PING, _OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
_HANDSHAKE_LIMIT = 65536


class WsError(Exception):
    pass


class WsClient:
    """One client connection. connect() performs TCP/TLS + the upgrade
    handshake; run() is the blocking receive loop (worker thread)."""

    def __init__(
        self,
        url: str,
        timeout: float,
        on_event: Callable[[str, Any], None],
    ) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("ws", "wss"):
            raise WsError(f"unsupported scheme {parsed.scheme!r} (expected ws:// or wss://)")
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        self._path = parsed.path or "/"
        if parsed.query:
            self._path += "?" + parsed.query
        self._tls = parsed.scheme == "wss"
        self._timeout = timeout
        self._on_event = on_event
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._open = False
        self._disconnected_emitted = False
        self._buffer = b""
        self._message: list[bytes] = []

    # -- connect / handshake ---------------------------------------------------

    def connect(self) -> None:
        sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        try:
            if self._tls:
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=self._host)
            key = base64.b64encode(os.urandom(16)).decode()
            request = (
                f"GET {self._path} HTTP/1.1\r\n"
                f"Host: {self._host}:{self._port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            )
            sock.sendall(request.encode("ascii"))
            head, rest = self._read_handshake(sock)
            status, headers = self._parse_handshake(head)
            if status != 101:
                raise WsError(f"handshake rejected: HTTP {status}")
            expected = base64.b64encode(hashlib.sha1(key.encode() + _GUID).digest()).decode()
            if headers.get("sec-websocket-accept") != expected:
                raise WsError("handshake failed: bad Sec-WebSocket-Accept")
            self._buffer = rest  # may already contain frame bytes
            self._sock = sock
            self._open = True
        except Exception:
            try:
                sock.close()
            except OSError:
                pass
            raise

    def _read_handshake(self, sock: socket.socket) -> tuple[bytes, bytes]:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                raise WsError("handshake: connection closed")
            data += chunk
            if len(data) > _HANDSHAKE_LIMIT:
                raise WsError("handshake response too large")
        return data.partition(b"\r\n\r\n")[0], data.partition(b"\r\n\r\n")[2]

    @staticmethod
    def _parse_handshake(head: bytes) -> tuple[int, dict[str, str]]:
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split(" ")[1])
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                headers[name.strip().lower()] = value.strip()
        return status, headers

    # -- receive loop ------------------------------------------------------------

    def run(self) -> None:
        try:
            while not self._stop.is_set() and self._sock is not None:
                self._sock.settimeout(0.5)
                try:
                    chunk = self._sock.recv(4096)
                except (socket.timeout, TimeoutError):
                    continue
                except (OSError, ssl.SSLError) as exc:
                    if not self._stop.is_set():
                        self._emit_disconnected(str(exc))
                    break
                if not chunk:
                    if not self._stop.is_set():
                        self._emit_disconnected(None)
                    break
                self._buffer += chunk
                self._parse_buffer()
        finally:
            self.close()

    def _parse_buffer(self) -> None:
        while True:
            frame = self._next_frame()
            if frame is None:
                return
            opcode, fin, payload = frame
            if opcode == _OP_PING:
                try:
                    self._send_frame(_OP_PONG, payload)
                except OSError:
                    pass
            elif opcode == _OP_PONG:
                pass
            elif opcode == _OP_CLOSE:
                try:
                    self._send_frame(_OP_CLOSE, payload)
                except OSError:
                    pass
                self._stop.set()
                self._emit_disconnected(None)
                return
            elif opcode in (_OP_TEXT, _OP_BINARY, _OP_CONT):
                self._message.append(payload)
                if fin:
                    data = b"".join(self._message)
                    self._message = []
                    if opcode == _OP_BINARY:
                        # binary -> latin-1: every byte preserved as a char
                        self._on_event("dataReceived", data.decode("latin-1"))
                    else:
                        self._on_event("dataReceived", data.decode("utf-8", errors="replace"))

    def _next_frame(self) -> tuple[int, bool, bytes] | None:
        buf = self._buffer
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        offset = 2
        if length == 126:
            if len(buf) < 4:
                return None
            length = struct.unpack(">H", buf[2:4])[0]
            offset = 4
        elif length == 127:
            if len(buf) < 10:
                return None
            length = struct.unpack(">Q", buf[2:10])[0]
            offset = 10
        mask = b""
        if masked:  # servers must not mask, but be lenient
            if len(buf) < offset + 4:
                return None
            mask = buf[offset : offset + 4]
            offset += 4
        if len(buf) < offset + length:
            return None
        payload = bytearray(buf[offset : offset + length])
        if mask:
            for i in range(len(payload)):
                payload[i] ^= mask[i % 4]
        self._buffer = buf[offset + length :]
        return opcode, fin, bytes(payload)

    # -- send / close -----------------------------------------------------------

    def _send_frame(
        self, opcode: int, payload: bytes, sock: socket.socket | None = None
    ) -> None:
        sock = sock or self._sock
        if sock is None:
            raise WsError("not connected")
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        masked = bytearray(payload)
        for i in range(len(masked)):
            masked[i] ^= mask[i % 4]
        sock.sendall(bytes(header) + mask + bytes(masked))

    def send(self, data: str) -> None:
        if not self._open or self._stop.is_set():
            raise WsError("socket not open")
        self._send_frame(_OP_TEXT, data.encode("utf-8"))

    def close(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None and self._open:
            try:
                self._send_frame(_OP_CLOSE, b"", sock)
            except OSError:
                pass
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._emit_disconnected(None)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self._open = False

    def is_open(self) -> bool:
        return self._open and not self._stop.is_set()

    def _emit_disconnected(self, detail: Any) -> None:
        if not self._disconnected_emitted:
            self._disconnected_emitted = True
            self._on_event("disconnected", detail)


class WebSocketPool:
    """Registry of WsClient connections keyed by connection id."""

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

    def connect(self, conn: int, url: str, timeout: float) -> tuple[bool, str | None]:
        entry = self._entry(conn)
        if entry is None:
            return False, "unknown connection"
        client = WsClient(url, timeout, lambda event, data: self._emit(conn, event, data))
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

    def send(self, conn: int, data: str) -> tuple[bool, str | None]:
        entry = self._entry(conn)
        client = entry["client"] if entry else None
        if client is None or not client.is_open():
            return False, "socket not open"
        try:
            client.send(data)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def is_open(self, conn: int) -> bool:
        entry = self._entry(conn)
        client = entry["client"] if entry else None
        return client is not None and client.is_open()

    def close(self, conn: int) -> bool:
        entry = self._entry(conn)
        client = entry["client"] if entry else None
        if client is None:
            return False
        client.close()
        return True

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
        """Open connections: they keep the process alive (pending work)."""
        with self._lock:
            return sum(
                1
                for entry in self._entries.values()
                if entry["client"] is not None and entry["client"].is_open()
            )