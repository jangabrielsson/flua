"""flua-mcp: the MCP server (stdio transport).

Model Context Protocol over newline-delimited JSON-RPC on stdin/stdout.
Stdout is pure JSON-RPC; server diagnostics go to stderr. Serves both the
2026-07-28 protocol era (per-request version in params._meta + server/discover)
and the legacy initialize era; implements tools and resources.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .. import __version__
from .jsonrpc import INVALID_PARAMS, METHOD_NOT_FOUND, JsonRpcError, run_stdio
from .prompts import get_prompt, list_prompts
from .resources import list_resources, read_resource
from .tools import _SESSIONS, TOOLS

# The 2026-07-28 revision dropped the initialize handshake: every request
# carries its protocol version in params._meta and servers MUST implement
# server/discover (the "modern" era). Older clients still send initialize
# (the "legacy" era, 2025-11-25 and earlier) — flua-mcp serves both.
SUPPORTED_VERSIONS = ["2026-07-28", "2025-06-18"]
LEGACY_PROTOCOL_VERSION = "2025-06-18"  # advertised to initialize-era clients
UNSUPPORTED_PROTOCOL_VERSION = -32022

SERVER_INSTRUCTIONS = (
    "flua-mcp runs Fibaro QuickApps in the flua emulator. Use qa_check to "
    "static-check QA files and qa_run to run them to completion; runs are "
    "offline by default and never touch a controller unless mode=remote. "
    "In terminals prefer the `flua` command over `python -m flua` — tool "
    "subprocesses use this server's interpreter, which may differ from the "
    "shell's default python."
)


def _check_protocol_version(msg: dict[str, Any]) -> None:
    """Modern per-request version negotiation: params._meta carries the
    client's protocol version; unsupported versions answer -32022.
    Requests without the field are legacy (the initialize era)."""
    meta = (msg.get("params") or {}).get("_meta") or {}
    version = meta.get("io.modelcontextprotocol/protocolVersion")
    if version is not None and version not in SUPPORTED_VERSIONS:
        raise JsonRpcError(
            UNSUPPORTED_PROTOCOL_VERSION,
            "Unsupported protocol version",
            {"supported": SUPPORTED_VERSIONS, "requested": version},
        )


def _initialize(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": LEGACY_PROTOCOL_VERSION,
        "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        "serverInfo": {"name": "flua-mcp", "version": __version__},
    }


def _discover(_params: dict[str, Any]) -> dict[str, Any]:
    """server/discover (2026-07-28, required): supported versions,
    capabilities, and identity in one request."""
    return {
        "resultType": "complete",
        "supportedVersions": SUPPORTED_VERSIONS,
        "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        "instructions": SERVER_INSTRUCTIONS,
        "_meta": {
            "io.modelcontextprotocol/serverInfo": {"name": "flua-mcp", "version": __version__}
        },
    }


def _tools_list(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "resultType": "complete",
        "tools": [
            {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
            for name, spec in TOOLS.items()
        ],
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
            "resultType": "complete",
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
    "server/discover": _discover,
    "initialize": _initialize,
    "ping": lambda _params: {},
    "tools/list": _tools_list,
    "tools/call": _tools_call,
    "resources/list": list_resources,
    "resources/read": read_resource,
    "prompts/list": list_prompts,
    "prompts/get": get_prompt,
    # client notifications: handled, never answered (the core drops the id)
    "notifications/initialized": lambda _params: None,
    "notifications/cancelled": lambda _params: None,
}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--version" in argv:
        supported = ", ".join(SUPPORTED_VERSIONS)
        print(f"flua-mcp {__version__} (protocols {supported})")
        return 0
    try:
        return run_stdio(METHODS, precheck=_check_protocol_version)
    finally:
        _SESSIONS.shutdown()  # never leak engines when the stdio pipe closes


if __name__ == "__main__":
    sys.exit(main())
