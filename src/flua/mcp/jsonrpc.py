"""JSON-RPC 2.0 over newline-delimited stdio — the MCP transport core.

No SDK: the protocol surface the MCP spec uses is small. One JSON object
per line; responses go to stdout (nothing else may), server-side logging to
stderr.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

# JSON-RPC 2.0 standard error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class JsonRpcError(Exception):
    """A request-level error with a JSON-RPC code (tools raise these for
    invalid arguments; the transport turns them into error responses)."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _result(response_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": response_id, "result": result}


def _error(response_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    return {"jsonrpc": "2.0", "id": response_id, "error": payload}


def handle_message(
    line: str, methods: dict[str, Callable[[dict[str, Any]], Any]]
) -> dict[str, Any] | None:
    """One newline-delimited JSON-RPC message -> the response to print, or
    None for notifications (no id) and for parse-level failures with no id
    to echo (per spec those answer with id null)."""
    try:
        msg = json.loads(line)
    except ValueError:
        return _error(None, PARSE_ERROR, "parse error")
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(
            msg.get("id") if isinstance(msg, dict) else None,
            INVALID_REQUEST,
            "invalid request",
        )
    method = msg.get("method")
    is_notification = "id" not in msg
    handler = methods.get(method) if isinstance(method, str) else None
    if handler is None:
        if is_notification:
            return None
        return _error(msg["id"], METHOD_NOT_FOUND, f"method not found: {method}")
    try:
        result = handler(msg.get("params") or {})
    except JsonRpcError as exc:
        if is_notification:
            return None
        return _error(msg["id"], exc.code, exc.message, exc.data)
    except Exception as exc:  # a handler bug: report it, never crash the server
        print(f"mcp: handler {method} failed: {exc}", file=sys.stderr)
        if is_notification:
            return None
        return _error(msg["id"], INTERNAL_ERROR, str(exc))
    if is_notification:
        return None
    return _result(msg["id"], result)


def run_stdio(methods: dict[str, Callable[[dict[str, Any]], Any]]) -> int:
    """The server loop: read JSON-RPC lines from stdin until EOF, write one
    response line per request. Returns the process exit code."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = handle_message(line, methods)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0
