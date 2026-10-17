"""flua-mcp: the Streamable HTTP transport (stateless mode).

One endpoint, plain JSON-RPC over HTTP — the 2026-07-28 stateless shape:
every request carries what it needs (explicit sessionIds for the session
tools), so no SSE, no transport-level sessions, no server-side request
state. Same dispatch core as stdio (``jsonrpc.handle_message``); the
transport only adds the HTTP envelope, auth, and size caps.

Safety is in the mechanism, not in prose: loopback-only by default, a
bearer token from the environment, non-loopback binds refuse to start
without one, and request bodies are size-capped.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import socket
import sys
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .jsonrpc import handle_message

MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MiB — docs and logs, never more
AUTH_ERROR_CODE = -32001  # server error range; the spec defines no auth code


def _error_body(message: str, code: int = AUTH_ERROR_CODE) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}}


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return all(ipaddress.ip_address(info[4][0]).is_loopback for info in infos)


class _Handler(BaseHTTPRequestHandler):
    """One POST /mcp per request; stateless per the 2026-07-28 spec."""

    server_version = "flua-mcp/1"

    def _cors(self) -> None:
        # browser-hosted clients call over fetch; wildcard works because
        # auth is a header, not a cookie
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization, Mcp-Session-Id"
        )
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def _json(
        self, status: int, payload: dict[str, Any], extra: tuple[tuple[str, str], ...] = ()
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in extra:
            self.send_header(name, value)
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _empty(self, status: int, extra: tuple[tuple[str, str], ...] = ()) -> None:
        self.send_response(status)
        for name, value in extra:
            self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_OPTIONS(self) -> None:  # CORS preflight
        self._empty(204)

    def do_GET(self) -> None:
        # stateless servers do not serve SSE: the spec says 405
        self._empty(405, (("Allow", "POST, OPTIONS"),))

    def do_DELETE(self) -> None:
        self._empty(405, (("Allow", "POST, OPTIONS"),))

    def do_POST(self) -> None:
        if self.path not in ("/mcp", "/mcp/"):
            self._json(404, _error_body(f"method not found: {self.path}", -32601))
            return
        if "Mcp-Session-Id" in self.headers:
            # transport-level sessions are someone else's; our sessions are
            # explicit sessionId tool arguments — the spec says 404
            self._json(404, _error_body("stateless server: no transport sessions"))
            return
        token: str | None = self.server.token  # type: ignore[attr-defined]
        if token is not None:
            auth = self.headers.get("Authorization", "")
            supplied = auth[7:] if auth.startswith("Bearer ") else ""
            if not hmac.compare_digest(supplied, token):
                self._json(
                    401,
                    _error_body("unauthorized: missing or invalid bearer token"),
                    (("WWW-Authenticate", "Bearer"),),
                )
                return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, _error_body("invalid Content-Length", -32600))
            return
        if length > MAX_BODY_BYTES:
            # answer without consuming the body, then drop the connection —
            # keep-alive cannot resume mid-body
            self._json(413, _error_body(f"body exceeds {MAX_BODY_BYTES} bytes"))
            self.close_connection = True
            return
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        response = handle_message(raw, self.server.methods, self.server.precheck)  # type: ignore[attr-defined]
        if response is None:  # a notification: 202, no body
            self._empty(202)
        else:
            self._json(200, response)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"flua-mcp http: {self.address_string()} {format % args}", file=sys.stderr)


class StreamableHttpServer:
    """A threaded Streamable HTTP server around the JSON-RPC dispatch core.

    ``host`` loopback-only unless a bearer token is set — the constructor
    refuses non-loopback binds without one."""

    def __init__(
        self,
        host: str,
        port: int,
        methods: dict[str, Callable[[dict[str, Any]], Any]],
        precheck: Callable[[dict[str, Any]], None] | None,
        token: str | None = None,
    ) -> None:
        if not _is_loopback(host) and token is None:
            raise ValueError(
                "refusing to bind a non-loopback address without FLUA_MCP_TOKEN "
                "(the server exposes device state and HC3 credentials)"
            )
        self.token = token
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.methods = methods  # type: ignore[attr-defined]
        self.httpd.precheck = precheck  # type: ignore[attr-defined]
        self.httpd.token = token  # type: ignore[attr-defined]

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    @property
    def host(self) -> str:
        return str(self.httpd.server_address[0])

    def serve_forever(self) -> None:
        auth = "bearer token required" if self.token else "no auth — loopback only"
        print(
            f"flua-mcp http: listening on http://{self.host}:{self.port}/mcp ({auth})",
            file=sys.stderr,
        )
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.httpd.shutdown()

    def server_close(self) -> None:
        self.httpd.server_close()


def serve_http(
    host: str,
    port: int,
    methods: dict[str, Callable[[dict[str, Any]], Any]],
    precheck: Callable[[dict[str, Any]], None] | None,
    token: str | None = None,
) -> int:
    server = StreamableHttpServer(host, port, methods, precheck, token=token)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0
