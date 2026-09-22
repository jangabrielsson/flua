"""HTTP server for the simulated HC3 REST API (the UI viewer's channel).

A tiny stdlib-only asyncio HTTP server wrapping :meth:`flua.api.Api.dispatch`
— the same dispatch the Lua ``api`` table uses in-process. The UI viewer (a
standalone static page, ``viewer/index.html``) polls ``/devices`` through it
and injects UI interactions via ``GET /plugins/callUIEvent``, exactly like a
real HC3 UI would.

Design notes:

- ``Connection: close`` per request — polling every second does not need
  keep-alive, and this keeps the parser trivial.
- Permissive CORS (``Access-Control-Allow-Origin: *``) so the viewer works
  from ``file://`` as well as any localhost origin.
- The server is NOT pending work: the engine's ``has_pending_work()`` does
  not look at it, so a drained run exits while the listener is still up. The
  CLI owns the task and stops it on exit.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .api import Api

logger = logging.getLogger(__name__)

_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


class ApiServer:
    """Serve an :class:`~flua.api.Api` over HTTP (loopback by default)."""

    def __init__(self, api: Api, host: str = "127.0.0.1", port: int = 8090) -> None:
        self.api = api
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Bind the listener; with port 0 the OS picks one (``self.port``)."""
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        if self.port == 0 and self._server.sockets:
            self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # -- request handling -------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await _read_request(reader)
            if request is None:  # empty/broken request line: bail quietly
                return
            method, target, headers, body = request
            if method == "OPTIONS":
                _respond(writer, 204, None, extra=_CORS)
                return
            path, _, query = target.partition("?")
            if query:
                path = f"{path}?{query}"
            data, status = self.api.dispatch(method, path, body)
            _respond(writer, status, data, extra=_CORS)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass  # the viewer moved on mid-request
        except _BadRequest:
            _respond(writer, 400, {"error": "invalid JSON body"}, extra=_CORS)
        except Exception:  # never let one request kill the server
            logger.exception("UI server: request failed")
            _respond(writer, 500, {"error": "internal error"}, extra=_CORS)


async def _read_request(
    reader: asyncio.StreamReader,
) -> tuple[str, str, dict[str, str], Any] | None:
    """Parse one HTTP/1.1 request: (method, target, headers, json-body)."""
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode("utf-8", "replace").split("\r\n")
    request_line = lines[0].split()
    if len(request_line) < 2:
        return None
    method, target = request_line[0], request_line[1]
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    body: Any = None
    if "content-length" in headers:
        length = int(headers["content-length"])
        if length > 0:
            payload = await reader.readexactly(length)
            text = payload.decode("utf-8", "replace")
            if text.strip():
                try:
                    body = json.loads(text)
                except ValueError:
                    raise _BadRequest(text) from None
    return method, target, headers, body


class _BadRequest(Exception):
    """Malformed JSON body."""


def _respond(
    writer: asyncio.StreamWriter,
    status: int,
    data: Any,
    extra: dict[str, str] | None = None,
) -> None:
    try:
        body = json.dumps(data).encode()
    except TypeError:
        body = json.dumps({"error": "response not serializable"}).encode()
        status = 500
    if status == 204:
        body = b""  # 204 responses carry no body
    reason = {200: "OK", 204: "No Content", 400: "Bad Request", 404: "Not Found"}.get(
        status, "OK"
    )
    head = [f"HTTP/1.1 {status} {reason}", "Content-Type: application/json"]
    head.append(f"Content-Length: {len(body)}")
    head.append("Connection: close")
    for key, value in (extra or {}).items():
        head.append(f"{key}: {value}")
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + body)
    writer.close()
