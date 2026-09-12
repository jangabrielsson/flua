"""Blocking TCP sockets for mobdebug compatibility.

mobdebug assumes synchronous LuaSocket semantics: receive() blocks until data
arrives. These functions use plain Python blocking sockets on the main thread,
which freezes the asyncio loop while the debugger waits — that is a feature:
while paused at a breakpoint, no timer callbacks fire and time effectively
stops for Lua. This is the one documented exception to flua's message-passing
model (direct calls that may block the loop).

Single-threaded by design: no locks, no cross-thread plumbing (unlike plua's
version, which carries a threading lock it never actually needs).
"""

import logging
import socket
import threading
from typing import Any

logger = logging.getLogger(__name__)


def _decode_or_none(data: bytes) -> str | None:
    return data.decode("utf-8", errors="replace") if data else None


class SyncTCPSockets:
    """Blocking, LuaSocket-compatible TCP sockets (the subset mobdebug uses).

    Single-threaded by design for the debugger, but a lock guards the
    registry so a second instance can serve net.TCPSocket operations from
    worker threads without racing (the debugger's instance never contends).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sockets: dict[int, socket.socket] = {}
        self._counter = 0

    # -- bookkeeping ----------------------------------------------------------

    def _register(self, sock: socket.socket) -> int:
        with self._lock:
            self._counter += 1
            self._sockets[self._counter] = sock
            return self._counter

    def _get(self, conn_id: int) -> socket.socket:
        with self._lock:
            sock = self._sockets.get(conn_id)
        if sock is None:
            raise ValueError(f"invalid connection id: {conn_id}")
        return sock

    # -- LuaSocket-compatible operations ----------------------------------------

    def connect(self, host: str, port: int, timeout: float = 1.0) -> tuple:
        """(True, conn_id) | (False, error_message)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            sock.connect((host, int(port)))
            return True, self._register(sock)
        except OSError as exc:
            sock.close()
            return False, f"connect: {exc}"

    def write(self, conn_id: int, data: str | bytes) -> tuple:
        """(True, bytes_sent) | (False, error_message)."""
        try:
            sock = self._get(conn_id)
            payload = data if isinstance(data, bytes) else str(data).encode("utf-8")
            return True, sock.send(payload)
        except OSError as exc:
            return False, f"send: {exc}"

    def read(self, conn_id: int, pattern: Any = "*l") -> tuple:
        """(True, data) | (False, "timeout"|"closed", partial_data)."""
        try:
            sock = self._get(conn_id)
            if pattern == "*a":
                return self._read_all(sock)
            if pattern == "*l":
                return self._read_line(sock)
            if isinstance(pattern, (int, float)):
                return self._read_bytes(sock, int(pattern))
            return False, f"unsupported receive pattern: {pattern!r}", None
        except ConnectionResetError:
            return False, "closed", None
        except OSError as exc:
            return False, f"read: {exc}", None

    def _read_line(self, sock: socket.socket) -> tuple:
        data = b""
        while True:
            try:
                byte = sock.recv(1)
            except (BlockingIOError, TimeoutError):
                return False, "timeout", _decode_or_none(data)
            except ConnectionResetError:
                return False, "closed", _decode_or_none(data)
            if not byte:
                return False, "closed", _decode_or_none(data)
            if byte == b"\n":
                if data.endswith(b"\r"):
                    data = data[:-1]
                return True, data.decode("utf-8", errors="replace")
            data += byte

    def _read_bytes(self, sock: socket.socket, n: int) -> tuple:
        if n <= 0:
            return True, ""
        data = b""
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
            except (BlockingIOError, TimeoutError):
                return False, "timeout", _decode_or_none(data)
            except ConnectionResetError:
                return False, "closed", _decode_or_none(data)
            if not chunk:
                return False, "closed", _decode_or_none(data)
            data += chunk
        return True, data.decode("utf-8", errors="replace")

    def _read_all(self, sock: socket.socket) -> tuple:
        parts: list[bytes] = []
        while True:
            try:
                chunk = sock.recv(4096)
            except (BlockingIOError, TimeoutError):
                return False, "timeout", _decode_or_none(b"".join(parts))
            except ConnectionResetError:
                return False, "closed", _decode_or_none(b"".join(parts))
            if not chunk:
                return True, b"".join(parts).decode("utf-8", errors="replace")
            parts.append(chunk)

    def read_chunk(self, conn_id: int, n: int = 4096) -> tuple:
        """One recv() — the next available data package, like the HC3's
        TCPSocket:read. (True, data) | (False, "timeout"|"closed", None)."""
        try:
            sock = self._get(conn_id)
            data = sock.recv(int(n))
        except (BlockingIOError, TimeoutError):
            return False, "timeout", None
        except ConnectionResetError:
            return False, "closed", None
        except OSError as exc:
            return False, f"read: {exc}", None
        if not data:
            return False, "closed", None
        return True, data.decode("utf-8", errors="replace"), None

    def read_until(self, conn_id: int, delimiter: str) -> tuple:
        """Read until ``delimiter`` appears (excluded from the result), like
        the HC3's TCPSocket:readUntil. (True, data) | (False, err, partial)."""
        sock = self._get(conn_id)
        data = b""
        needle = delimiter.encode("utf-8")
        while True:
            try:
                byte = sock.recv(1)
            except (BlockingIOError, TimeoutError):
                return False, "timeout", _decode_or_none(data)
            except ConnectionResetError:
                return False, "closed", _decode_or_none(data)
            except OSError as exc:
                return False, f"read: {exc}", _decode_or_none(data)
            if not byte:
                return False, "closed", _decode_or_none(data)
            data += byte
            if data.endswith(needle):
                return True, data[: -len(needle)].decode("utf-8", errors="replace"), None

    def set_timeout(self, conn_id: int, timeout: float | None) -> tuple:
        """None = blocking, 0 = non-blocking, t > 0 = timeout in seconds."""
        try:
            sock = self._get(conn_id)
            sock.settimeout(timeout)
            return True, ""
        except OSError as exc:
            return False, f"settimeout: {exc}"

    def close(self, conn_id: int) -> tuple:
        with self._lock:
            sock = self._sockets.pop(conn_id, None)
        if sock is None:
            return False, "invalid connection id"
        try:
            sock.close()
        except OSError:
            pass
        return True, ""

    def bind(self, host: str, port: int) -> tuple:
        """(True, server_id) | (False, error_message). Used by mobdebug.listen()."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("" if host == "*" else host, int(port)))
            sock.listen(4)
            return True, self._register(sock)
        except OSError as exc:
            sock.close()
            return False, f"bind: {exc}"

    def getsockname(self, conn_id: int) -> tuple:
        """(True, ip, port) | (False, error_message)."""
        try:
            sock = self._get(conn_id)
            addr = sock.getsockname()
            return True, addr[0], addr[1]
        except OSError as exc:
            return False, f"getsockname: {exc}"

    def accept(self, server_id: int) -> tuple:
        """(True, conn_id) | (False, error_message). Blocks like LuaSocket."""
        try:
            sock = self._get(server_id)
            client, _ = sock.accept()
            client.settimeout(None)
            return True, self._register(client)
        except OSError as exc:
            return False, f"accept: {exc}"

    def close_all(self) -> None:
        with self._lock:
            socks = list(self._sockets.values())
            self._sockets.clear()
        for sock in socks:
            try:
                sock.close()
            except OSError:
                pass

    def connection_count(self) -> int:
        return len(self._sockets)


class SyncUDPSockets:
    """Blocking UDP datagram sockets for net.UDPSocket (worker threads)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sockets: dict[int, socket.socket] = {}
        self._counter = 0

    def _register(self, sock: socket.socket) -> int:
        with self._lock:
            self._counter += 1
            self._sockets[self._counter] = sock
            return self._counter

    def _get(self, conn_id: int) -> socket.socket:
        with self._lock:
            sock = self._sockets.get(conn_id)
        if sock is None:
            raise ValueError(f"invalid connection id: {conn_id}")
        return sock

    def open(self, port: int = 0, broadcast: bool = False, timeout: float | None = None) -> tuple:
        """(True, conn_id, bound_port) | (False, error_message, None)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("", int(port)))
            if broadcast:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            if timeout is not None:
                sock.settimeout(timeout)
            return True, self._register(sock), sock.getsockname()[1]
        except OSError as exc:
            sock.close()
            return False, f"bind: {exc}", None

    def send_to(self, conn_id: int, data: str, ip: str, port: int) -> tuple:
        """(True, bytes_sent) | (False, error_message)."""
        try:
            sock = self._get(conn_id)
            return True, sock.sendto(data.encode("utf-8"), (str(ip), int(port)))
        except OSError as exc:
            return False, f"sendto: {exc}"

    def receive(self, conn_id: int) -> tuple:
        """(True, data) | (False, "timeout"|err, None). One datagram."""
        try:
            sock = self._get(conn_id)
            data, _addr = sock.recvfrom(65535)
        except (BlockingIOError, TimeoutError):
            return False, "timeout", None
        except OSError as exc:
            return False, f"receive: {exc}", None
        return True, data.decode("utf-8", errors="replace"), None

    def close(self, conn_id: int) -> tuple:
        with self._lock:
            sock = self._sockets.pop(conn_id, None)
        if sock is None:
            return False, "invalid connection id"
        try:
            sock.close()
        except OSError:
            pass
        return True, ""

    def close_all(self) -> None:
        with self._lock:
            socks = list(self._sockets.values())
            self._sockets.clear()
        for sock in socks:
            try:
                sock.close()
            except OSError:
                pass