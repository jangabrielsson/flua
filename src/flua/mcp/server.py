"""flua-mcp: the MCP server (stdio transport).

Model Context Protocol over newline-delimited JSON-RPC on stdin/stdout.
Stdout is pure JSON-RPC; server diagnostics go to stderr. The protocol
version follows the 2025-06-18 MCP spec (stateless sessions allowed);
only the initialize/tools surface is implemented so far.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .. import __version__
from .jsonrpc import INVALID_PARAMS, METHOD_NOT_FOUND, JsonRpcError, run_stdio
from .tools import TOOLS

PROTOCOL_VERSION = "2025-06-18"


def _initialize(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "flua-mcp", "version": __version__},
    }


def _tools_list(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "tools": [
            {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
            for name, spec in TOOLS.items()
        ]
    }


def _tools_call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    spec = TOOLS.get(name)
    if spec is None:
        raise JsonRpcError(METHOD_NOT_FOUND, f"unknown tool: {name}")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise JsonRpcError(INVALID_PARAMS, "arguments must be an object")
    try:
        result = spec["handler"](arguments)
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": False,
        }
    except JsonRpcError as exc:
        # tool-level failures travel in the result, not as JSON-RPC errors
        return {"content": [{"type": "text", "text": exc.message}], "isError": True}


def _dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


METHODS: dict[str, Any] = {
    "initialize": _initialize,
    "ping": lambda _params: {},
    "tools/list": _tools_list,
    "tools/call": _tools_call,
    # client notifications: handled, never answered (the core drops the id)
    "notifications/initialized": lambda _params: None,
    "notifications/cancelled": lambda _params: None,
}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--version" in argv:
        print(f"flua-mcp {__version__} (protocol {PROTOCOL_VERSION})")
        return 0
    return run_stdio(METHODS)


if __name__ == "__main__":
    sys.exit(main())
