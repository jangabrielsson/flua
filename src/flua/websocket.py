"""Minimal RFC 6455 WebSocket client (blocking; runs in worker threads).

No external dependencies — stdlib sockets + ssl, keeping lupa the only
runtime requirement. One thread per connection runs the receive loop;
events (connected/disconnected/error/dataReceived) are handed to the
engine through a thread-safe callback and delivered to QA code via the
pump, like the other net.* classes.

Data fidelity: sends are UTF-8 text frames (sendBinary sends binary
frames). Text frames arrive decoded as UTF-8; binary frames arrive as raw
bytes with the dataReceived listener's isBinary flag true (the new HC3
binary mode), so MQTT-over-WSS style protocols work end to end.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import socket
import ssl
import struct
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_OP_CONT, _OP_TEXT, _OP_BINARY, _OP_CLOSE, _OP_PING, _OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
_HANDSHAKE_LIMIT = 65536


class WsError(Exception):
    pass


_OP_NAMES = {0x0: "cont", 0x1: "text", 0x2: "binary", 0x8: "close", 0x9: "ping", 0xA: "pong"}

# debug-trace masking: never leak credential-ish values into the ws trace
_MASK_RE = re.compile(r'("(?:auth|token|access_token|password|Authorization)"\s*:\s*")[^"]*(")')


def _mask_secrets(text: str) -> str:
    return _MASK_RE.sub(r"\1***\2", text)


def _trace_preview(opcode: int, payload: bytes) -> str:
    """A short, secret-masked preview for --%%debug:ws frame lines."""
    if opcode == 0x2:  # binary: hex, no secrets to mask
        return payload[:32].hex() + ("..." if len(payload) > 32 else "")
    text = _mask_secrets(payload.decode("utf-8", errors="replace"))
    if len(text) > 64:
        text = text[:64] + "..."
    return repr(text)


class WsClient:
    """One client connection. connect() performs TCP/TLS + the upgrade
    handshake; run() is the blocking receive loop (worker thread)."""

    def __init__(
        self,
        url: str,
        timeout: float,
        on_event: Callable[[str, Any], None],
        headers: dict[str, str] | None = None,
        check_certificate: bool = False,
        trace: Callable[[str], None] | None = None,
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
        # the HC3's WebSocketClientTls does NOT verify certificates by
        # default (embedded bridges ship self-signed certs — e.g. Dirigera);
        # flua mirrors that. check_certificate=True opts back in.
        self._check_certificate = check_certificate
        self._timeout = timeout
        self._on_event = on_event
        self._trace = trace
        self._headers = headers or {}
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._open = False
        self._disconnected_emitted = False
        self._close_sent = False
        # SSL_write is not thread-safe: sends arrive from the engine's
        # thread pool (one thread per wsSend) and the receiver thread
        # writes pong/close replies — one writer at a time, ever.
        self._write_lock = threading.Lock()
        self._buffer = b""
        self._message: list[bytes] = []

    # -- connect / handshake ---------------------------------------------------

    def _trace_line(self, text: str) -> None:
        if self._trace is not None:
            self._trace(text)

    def connect(self) -> None:
        sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        try:
            if self._tls:
                context = (
                    ssl.create_default_context()
                    if self._check_certificate
                    else ssl._create_unverified_context()
                )
                sock = context.wrap_socket(sock, server_hostname=self._host)
            key = base64.b64encode(os.urandom(16)).decode()
            extra = ""
            for name, value in self._headers.items():
                n = str(name).strip()
                v = str(value).strip()
                if not n or "\r" in n or "\n" in n or "\r" in v or "\n" in v:
                    raise WsError("invalid websocket header")
                if n.lower() == "sec-websocket-protocol":
                    # the HC3's subprotocol handling: the value splits on
                    # commas and each entry is a requested subprotocol — an
                    # empty value omits the header, a non-HTTP-token entry
                    # is a connect error, and the request joins the entries
                    # in the canonical ", " form (wire bytes unchanged)
                    if not v:
                        continue
                    entries = [entry.strip() for entry in v.split(",")]
                    if any(
                        not entry
                        or re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", entry) is None
                        for entry in entries
                    ):
                        raise WsError(
                            f"invalid Sec-WebSocket-Protocol value {v!r}: "
                            "subprotocols must be comma-separated HTTP tokens"
                        )
                    v = ", ".join(entries)
                extra += f"{n}: {v}\r\n"
            request = (
                f"GET {self._path} HTTP/1.1\r\n"
                f"Host: {self._host}:{self._port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                f"{extra}"
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
            self._trace_line(
                "connect handshake ok"
                + (f", buffered {len(rest)} bytes after connect" if rest else "")
            )
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
            if self._sock is not None:
                # Blocking reads: a recv poll via settimeout() can land
                # mid-TLS-record (CPython's ssl object then cannot resume the
                # read and the next call fails fatally — the "EOF occurred in
                # violation of protocol" / EAGAIN teardown). Instead the
                # receiver blocks until data or close(): close() wakes it
                # with shutdown(). Sends keep a cap via SO_SNDTIMEO (the
                # ssl layer stays in blocking mode, so the kernel enforces
                # it) — a stalled peer cannot hang a wsSend thread forever.
                self._sock.settimeout(None)
                if self._timeout:
                    sec = int(self._timeout)
                    usec = int((self._timeout - sec) * 1e6)
                    self._sock.setsockopt(
                        socket.SOL_SOCKET, socket.SO_SNDTIMEO, struct.pack("ll", sec, usec)
                    )
            while not self._stop.is_set() and self._sock is not None:
                # Frames may already sit in the buffer from the handshake read
                # (a server can send data in the same segment as its 101
                # response — Home Assistant does this with auth_required).
                # Parse them before blocking on recv, or they stay stuck until
                # the next chunk arrives.
                if self._buffer:
                    self._parse_buffer()
                    if self._stop.is_set() or self._sock is None:
                        break
                try:
                    chunk = self._sock.recv(4096)
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
            self._trace_line(
                f"rx {_OP_NAMES.get(opcode, opcode)} {len(payload)}b "
                f"{_trace_preview(opcode, payload)}"
            )
            if opcode == _OP_PING:
                try:
                    self._send_frame(_OP_PONG, payload)
                except (OSError, WsError):
                    pass  # socket gone (close raced the echo) — best effort
            elif opcode == _OP_PONG:
                pass
            elif opcode == _OP_CLOSE:
                code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else None
                reason = payload[2:].decode("utf-8", errors="replace") if len(payload) > 2 else ""
                self._trace_line(f"rx close code={code} reason={reason!r}")
                try:
                    self._send_frame(_OP_CLOSE, payload)
                except (OSError, WsError):
                    pass  # the socket was detached by close() — nothing to echo on
                self._stop.set()
                self._emit_disconnected(None)
                return
            elif opcode in (_OP_TEXT, _OP_BINARY, _OP_CONT):
                self._message.append(payload)
                if fin:
                    data = b"".join(self._message)
                    self._message = []
                    if opcode == _OP_BINARY:
                        # raw bytes + the isBinary flag (the HC3 binary mode)
                        self._on_event("dataReceived", data, True)
                    else:
                        text = data.decode("utf-8", errors="replace")
                        self._on_event("dataReceived", text, False)

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

    def _send_frame(self, opcode: int, payload: bytes, sock: socket.socket | None = None) -> None:
        sock = sock or self._sock
        if sock is None:
            raise WsError("not connected")
        self._trace_line(
            f"tx {_OP_NAMES.get(opcode, opcode)} {len(payload)}b "
            f"{_trace_preview(opcode, payload)}"
        )
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
        with self._write_lock:
            if opcode == _OP_CLOSE:
                if self._close_sent:
                    # RFC 6455: one close frame per endpoint. A close echoed
                    # by the receive loop must not be repeated by close().
                    return
                self._close_sent = True
            # NOTE: SO_SNDTIMEO caps writes at self._timeout (set in run()),
            # so a stalled peer fails the send instead of hanging the writer
            # thread forever. Writers never touch settimeout() themselves:
            # mutating the SSLSocket's timeout state concurrently with the
            # receiver's in-flight read breaks the read (EAGAIN teardown).
            sock.sendall(bytes(header) + mask + bytes(masked))

    def send(self, data: str) -> None:
        if not self._open or self._stop.is_set():
            raise WsError("socket not open")
        self._send_frame(_OP_TEXT, data.encode("utf-8"))

    def send_binary(self, data: bytes) -> None:
        if not self._open or self._stop.is_set():
            raise WsError("socket not open")
        self._send_frame(_OP_BINARY, data)

    def close(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None and self._open:
            try:
                self._send_frame(_OP_CLOSE, b"", sock)
            except OSError:
                pass
            with self._write_lock:
                # never tear the socket down under an in-flight sendall:
                # the write lock makes shutdown/close wait for the writers
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            self._emit_disconnected(None)
        if sock is not None:
            with self._write_lock:
                try:
                    sock.close()
                except OSError:
                    pass
        self._open = False

    def is_open(self) -> bool:
        return self._open and not self._stop.is_set()

    def _emit_disconnected(self, detail: Any) -> None:
        self._trace_line(f"disconnected: {detail}")
        if not self._disconnected_emitted:
            self._disconnected_emitted = True
            self._on_event("disconnected", detail)


class WebSocketPool:
    """Registry of WsClient connections keyed by connection id."""

    def __init__(
        self,
        emit: Callable[[int, str, Any], None],
        trace: Callable[[str], None] | None = None,
    ) -> None:
        self._emit = emit
        self._trace = trace
        self._lock = threading.Lock()
        self._entries: dict[int, dict[str, Any]] = {}  # conn -> {client, qa}
        self._close_requested: set[int] = set()  # close() raced the handshake
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
        self,
        conn: int,
        url: str,
        timeout: float,
        headers: dict[str, str] | None = None,
        check_certificate: bool = False,
    ) -> tuple[bool, str | None]:
        entry = self._entry(conn)
        if entry is None:
            return False, "unknown connection"
        client = WsClient(
            url,
            timeout,
            lambda event, data, is_binary=False: self._emit(conn, event, data, is_binary),
            headers,
            check_certificate,
            # label every trace line with the connection: with 2-4 concurrent
            # sockets (Sonos: household + per-player) a flat tx/rx stream is
            # unreadable — ws[c3 192.168.50.223] tx … identifies the socket
            (lambda line: self._trace(f"ws[c{conn} {urlparse(url).hostname or ''}] {line}"))
            if self._trace is not None
            else None,
        )
        try:
            client.connect()
        except Exception as exc:
            return False, str(exc)
        with self._lock:
            entry["client"] = client
            if conn in self._close_requested:
                # close() arrived while the handshake was in flight: the HC3
                # closes the socket as soon as the handshake finishes and
                # delivers only disconnected — connected is never fired
                self._close_requested.discard(conn)
                close_early = True
            else:
                close_early = False
        if close_early:
            client.close()
        return True, None

    def start_receiver(self, conn: int) -> None:
        entry = self._entry(conn)
        client = entry["client"] if entry else None
        if client is not None:
            threading.Thread(target=client.run, daemon=True).start()

    def send(self, conn: int, data: str | bytes, binary: bool = False) -> tuple[bool, str | None]:
        entry = self._entry(conn)
        client = entry["client"] if entry else None
        if client is None or not client.is_open():
            return False, "socket not open"
        if binary:
            payload = data if isinstance(data, bytes) else str(data).encode("utf-8")
            opcode = _OP_BINARY
        else:
            payload = str(data).encode("utf-8")
            opcode = _OP_TEXT
        try:
            if binary:
                client.send_binary(payload)
            else:
                client.send(str(data))
            return True, None
        except Exception as exc:
            # the QA's error event names the failed frame (masked preview),
            # so a burst failure can be attributed without leaking secrets
            return False, f"{exc} (frame: {_trace_preview(opcode, payload)})"

    def is_open(self, conn: int) -> bool:
        entry = self._entry(conn)
        client = entry["client"] if entry else None
        return client is not None and client.is_open()

    def close(self, conn: int) -> bool:
        entry = self._entry(conn)
        client = entry["client"] if entry else None
        if client is None:
            if entry is not None:
                # the handshake is still in flight: remember the request —
                # connect() closes the socket the moment it completes and
                # connected is never delivered
                with self._lock:
                    self._close_requested.add(conn)
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
