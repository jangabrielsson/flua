"""net.*Server hosts: asyncio-native mock servers owned by the engine.

flua extension (no HC3 counterpart): a QA hosts HTTP/TCP/UDP/WebSocket
servers in Lua so tests can mock the services a QA's net.* clients talk to.
The listening socket is bound synchronously when the QA calls listen (so
port 0 resolves to its real port immediately), and serving happens on the
engine's event loop. Every incoming request posts a ``serverRequest``
message into the pump; the QA's handler runs there, and its return value
comes back through the ``net_server_reply`` bridge call (synchronous — the
pump runs on the loop thread), resolving the connection's future, which
writes the wire response.

Semantics are deliberately simple (request/response, one shot):

- HTTP: full request in (method/url/headers/body), response out.
- TCP: the handler receives the first data package the peer sends; its
  reply is written back and the connection closes.
- UDP: one datagram in, optional reply datagram out.
- WebSocket: one message in, optional reply message out (text frames;
  binary replies echo byte-safe).

All servers bind 127.0.0.1 only.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import socket
import struct
from typing import Any

from . import messages

logger = logging.getLogger(__name__)

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_MESSAGE = 1 << 20  # 1 MB per HTTP body / WS message / TCP data package
_HANDLER_TIMEOUT = 10.0  # seconds a QA handler may take before the reply is dropped

_REASONS = {
    200: "OK",
    204: "No Content",
    400: "Bad Request",
    404: "Not Found",
    500: "Internal Server Error",
    504: "Gateway Timeout",
}

_TIMEOUT = object()  # sentinel: the QA handler never replied in time


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("latin-1", errors="replace")


# -- HTTP framing ---------------------------------------------------------------


async def _read_http_request(
    reader: asyncio.StreamReader,
) -> tuple[str, str, dict[str, str], str] | None:
    line = await reader.readline()
    if not line:
        return None
    try:
        method, target, _ = line.decode("latin-1").split(" ", 2)
    except ValueError:
        return None
    headers: dict[str, str] = {}
    while True:
        header = await reader.readline()
        if header in (b"\r\n", b"\n", b""):
            break
        name, _, value = header.decode("latin-1").partition(":")
        headers[name.strip().lower()] = value.strip()
    length = 0
    if headers.get("content-length"):
        with contextlib.suppress(ValueError):
            length = int(headers["content-length"])
    if length > _MAX_MESSAGE:
        return None
    body = (await reader.readexactly(length)).decode("latin-1") if length else ""
    return method.upper(), target, headers, body


def _http_response(response: Any) -> tuple[int, str, dict[str, str]]:
    if isinstance(response, dict):
        status = int(response.get("status") or 200)
        body = response.get("body") or ""
        headers = {str(k): str(v) for k, v in (response.get("headers") or {}).items()}
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
            headers.setdefault("Content-Type", "application/json")
        else:
            body = str(body)
    elif response is None:
        status, body, headers = 204, "", {}
    else:
        status, body, headers = 200, str(response), {"Content-Type": "text/plain"}
    return status, body, headers


async def _write_http_response(
    writer: asyncio.StreamWriter, status: int, body: str, headers: dict[str, str]
) -> None:
    data = body.encode("utf-8")
    known = {k.lower() for k in headers}
    if "content-length" not in known:
        headers["Content-Length"] = str(len(data))
    headers["Connection"] = "close"
    head = [f"HTTP/1.1 {status} {_REASONS.get(status, '')}".rstrip()]
    head.extend(f"{name}: {value}" for name, value in headers.items())
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + data)
    await writer.drain()


# -- WebSocket framing ----------------------------------------------------------


def _ws_frame(opcode: int, payload: bytes) -> bytes:
    """Server-side frame: unmasked (RFC 6455 — only clients mask)."""
    header = bytes([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header += bytes([length])
    elif length < 65536:
        header += bytes([126]) + struct.pack(">H", length)
    else:
        header += bytes([127]) + struct.pack(">Q", length)
    return header + payload


async def _read_ws_frame(reader: asyncio.StreamReader) -> tuple[int, bytes] | None:
    """One complete frame: (opcode, payload). Clients must mask."""
    header = await reader.readexactly(2)
    b1, b2 = header[0], header[1]
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", await reader.readexactly(8))[0]
    if length > _MAX_MESSAGE:
        raise ValueError("ws frame too large")
    mask = await reader.readexactly(4) if masked else None
    payload = bytearray(await reader.readexactly(length))
    if mask:
        for i in range(length):
            payload[i] ^= mask[i % 4]
    return opcode, bytes(payload)


# -- the host --------------------------------------------------------------------


class _Server:
    """One listening server of one kind."""

    def __init__(self, host: ServerHost, server_id: int, kind: str, port: int, qa: int) -> None:
        self.host = host
        self.sid = server_id
        self.kind = kind
        self.qa = qa
        self.sock = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM if kind == "udp" else socket.SOCK_STREAM
        )
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        if kind != "udp":
            self.sock.listen(64)
        self.port = int(self.sock.getsockname()[1])
        self._tasks: list[asyncio.Task[Any]] = []
        self.udp_transport: asyncio.DatagramTransport | None = None

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.sock.setblocking(False)
        if self.kind == "udp":
            task = loop.create_task(
                loop.create_datagram_endpoint(lambda: _UdpProtocol(self), sock=self.sock),
                name=f"flua-server-{self.kind}-{self.sid}",
            )
        else:
            task = loop.create_task(self._accept(), name=f"flua-server-{self.kind}-{self.sid}")
        self._tasks.append(task)

    def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        with contextlib.suppress(OSError):
            self.sock.close()

    # -- connection plumbing

    def _new_conn(self) -> int:
        conn = self.host._next_conn
        self.host._next_conn += 1
        return conn

    def _post(self, conn: int, **fields: Any) -> asyncio.Future[Any]:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self.host._pending[(self.sid, conn)] = fut
        self.host._engine.enqueue_outbound(
            messages.server_request(self.sid, conn, self.kind, self.qa, **fields)
        )
        return fut

    async def _await(self, fut: asyncio.Future[Any]) -> Any:
        try:
            return await asyncio.wait_for(fut, _HANDLER_TIMEOUT)
        except TimeoutError:
            return _TIMEOUT

    async def _streams(
        self, sock: socket.socket
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=_MAX_MESSAGE, loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await loop.create_connection(lambda: protocol, sock=sock)
        return reader, asyncio.StreamWriter(transport, protocol, reader, loop=loop)

    async def _accept(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                sock, _ = await loop.sock_accept(self.sock)
                handler = (
                    self._http_conn
                    if self.kind == "http"
                    else self._ws_conn
                    if self.kind == "ws"
                    else self._tcp_conn
                )
                task = loop.create_task(
                    handler(sock), name=f"flua-server-{self.kind}-conn-{self.sid}"
                )
                self._tasks.append(task)
        except asyncio.CancelledError:
            raise
        except OSError:
            pass  # closed

    async def _http_conn(self, sock: socket.socket) -> None:
        reader, writer = await self._streams(sock)
        try:
            request = await _read_http_request(reader)
            if request is None:
                return
            method, target, headers, body = request
            conn = self._new_conn()
            fut = self._post(conn, method=method, url=target, headers=headers, body=body)
            response = await self._await(fut)
            if response is _TIMEOUT:
                response = {"status": 504, "body": "no handler reply"}  # never answered
            status, rbody, rheaders = _http_response(response)
            await _write_http_response(writer, status, rbody, rheaders)
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    async def _tcp_conn(self, sock: socket.socket) -> None:
        reader, writer = await self._streams(sock)
        try:
            data = await reader.read(_MAX_MESSAGE)  # the first data package
            if data in (b"", None):
                return
            conn = self._new_conn()
            fut = self._post(conn, data=data.decode("latin-1"))
            response = await self._await(fut)
            if response is not _TIMEOUT and response:
                writer.write(_to_bytes(response))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    async def _ws_conn(self, sock: socket.socket) -> None:
        reader, writer = await self._streams(sock)
        try:
            request = await _read_http_request(reader)  # the upgrade request
            if request is None:
                return
            _, _, headers, _ = request
            key = headers.get("sec-websocket-key")
            if not key:
                await _write_http_response(writer, 400, "missing Sec-WebSocket-Key", {})
                return
            accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
            writer.write(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode("latin-1")
            )
            await writer.drain()
            while True:
                frame = await _read_ws_frame(reader)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:  # close
                    writer.write(_ws_frame(0x8, b""))
                    await writer.drain()
                    break
                if opcode == 0x9:  # ping -> pong
                    writer.write(_ws_frame(0xA, payload))
                    await writer.drain()
                    continue
                if opcode == 0xA:  # pong
                    continue
                if opcode in (0x1, 0x2):
                    binary = opcode == 0x2
                    # text: UTF-8; binary: latin-1 byte-safe, like the client
                    message = (
                        payload.decode("utf-8", errors="replace")
                        if not binary
                        else payload.decode("latin-1")
                    )
                    conn = self._new_conn()
                    fut = self._post(conn, message=message, binary=binary)
                    response = await self._await(fut)
                    if response is not _TIMEOUT and response:
                        # binary echoes go back as binary frames (byte-safe,
                        # latin-1); text replies are UTF-8 text frames
                        raw = _to_bytes(response) if binary else str(response).encode("utf-8")
                        writer.write(_ws_frame(0x2 if binary else 0x1, raw))
                        await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: _Server) -> None:
        self._server = server

    def connection_made(self, transport: asyncio.BaseTransport) -> None:  # noqa: D102
        self._server.udp_transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: Any) -> None:  # noqa: D102
        server = self._server
        host, port = addr
        conn = server._new_conn()
        fut = server._post(conn, data=data.decode("latin-1"), addr=str(host), port=int(port))

        async def reply() -> None:
            response = await server._await(fut)
            if response is not _TIMEOUT and response and server.udp_transport is not None:
                server.udp_transport.sendto(_to_bytes(response), (host, port))

        server._tasks.append(asyncio.get_running_loop().create_task(reply()))


class ServerHost:
    """Owns every net.*Server started by the QAs."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._servers: dict[int, _Server] = {}
        self._pending: dict[tuple[int, int], asyncio.Future[Any]] = {}
        self._next_id = 1
        self._next_conn = 1

    def start(self, kind: str, port: int, qa: int) -> tuple[int, int]:
        """Bind synchronously (so port 0 resolves at once) and serve. Raises
        OSError when the port is taken — the QA sees it as a Lua error."""
        kind = str(kind).lower()
        if kind not in ("http", "tcp", "udp", "ws"):
            raise ValueError(f"unknown server kind: {kind}")
        server_id = self._next_id
        self._next_id += 1
        server = _Server(self, server_id, kind, int(port), int(qa))
        try:
            server.start()
        except RuntimeError:
            server.close()
            raise
        self._servers[server_id] = server
        return server_id, server.port

    def reply(self, server_id: int, conn_id: int, response: Any) -> None:
        """The QA handler's return value (called from the pump, loop thread)."""
        fut = self._pending.pop((server_id, conn_id), None)
        if fut is not None and not fut.done():
            fut.set_result(response)

    def close_server(self, server_id: int) -> None:
        server = self._servers.pop(server_id, None)
        if server is not None:
            server.close()

    def close_qa(self, qa: int) -> None:
        for server_id in [sid for sid, server in self._servers.items() if server.qa == qa]:
            self.close_server(server_id)

    def close_all(self) -> None:
        for server in list(self._servers.values()):
            server.close()
        self._servers.clear()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result(None)
        self._pending.clear()
