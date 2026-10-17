"""The MCP tool registry: name, JSON-Schema input, handler.

V1 tools wrap what flua already ships — one-shot semantics identical to the
CLI, so the tool results can never drift from the documented flags.
Sessions (qa_start/qa_probe/…) come later on the in-process engine
(notes-mcp.md). Handlers return plain JSON; the server wraps it in MCP
content blocks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from ..check import check_file
from ..engine import LuaEngine
from .jsonrpc import INTERNAL_ERROR, INVALID_PARAMS, JsonRpcError

Tool = dict[str, Any]


def _file_list(args: dict[str, Any]) -> list[str]:
    files = args.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, str) for f in files):
        raise JsonRpcError(INVALID_PARAMS, "files must be a non-empty list of paths")
    return files


def _qa_check(args: dict[str, Any]) -> dict[str, Any]:
    """Static checks — the same layers as ``flua --check``: syntax, --%%
    directives, deprecated APIs, --%%file includes."""
    engine = LuaEngine()  # the compile-only lupa runtime
    lua = engine.lua_runtime()
    findings: list[dict[str, Any]] = []
    for path in _file_list(args):
        for line in check_file(path, lua):
            file, _, rest = line.partition(": ")
            severity, _, message = rest.partition(": ")
            findings.append({"file": file, "severity": severity, "message": message})
    return {"ok": not any(f["severity"] == "error" for f in findings), "findings": findings}


def _qa_run(args: dict[str, Any]) -> dict[str, Any]:
    """Run QA files to completion (the offline sim by default) and return
    the exit code, the JSON log lines, and the stderr verdict lines."""
    mode = args.get("mode")
    if mode not in (None, "local", "remote"):
        raise JsonRpcError(INVALID_PARAMS, "mode must be 'local' or 'remote'")
    timeout = args.get("timeout")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise JsonRpcError(INVALID_PARAMS, "timeout must be a positive number of seconds")
    command = [sys.executable, "-m", "flua", "--log", "json"]
    if mode is not None:
        command += ["--api", mode]
    if args.get("instant"):
        command.append("--instant")
    if args.get("speed") is not None:
        command += ["--speed", str(args["speed"])]
    if args.get("start") is not None:
        command += ["--start", str(args["start"])]
    command += _file_list(args)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout if timeout is not None else 120.0,
        )
    except subprocess.TimeoutExpired:
        raise JsonRpcError(
            INTERNAL_ERROR, f"run timed out after {timeout if timeout is not None else 120}s"
        ) from None
    logs: list[Any] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            logs.append(json.loads(line))
        except ValueError:
            logs.append(line)  # never drop a line over a formatting surprise
    return {
        "exitCode": result.returncode,
        "logs": logs,
        "verdict": [line for line in result.stderr.splitlines() if line.strip()],
    }


TOOLS: dict[str, Tool] = {
    "qa_check": {
        "description": (
            "Static-check QA files without running them: Lua syntax, unknown --%% "
            "directives, deprecated HC3 APIs, and every --%%file include. Returns "
            "{ok, findings:[{file, severity, message}]} — ok is false when any "
            "finding has severity 'error'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "QA main files to check (absolute or cwd-relative paths)",
                },
            },
            "required": ["files"],
        },
        "handler": _qa_check,
    },
    "qa_run": {
        "description": (
            "Run QA files to completion in the emulator (offline sim by default; "
            "mode 'remote' uses the real HC3 via the environment's credentials). "
            "Returns {exitCode, logs, verdict}: logs are the QA's --log json lines, "
            "verdict the stderr notices. One-shot — the run ends when the QAs drain; "
            "interactive probing is a later session tool."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "QA files to run (absolute or cwd-relative paths)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["local", "remote"],
                    "description": "engine mode (default: the offline sim)",
                },
                "instant": {
                    "type": "boolean",
                    "description": "instant mode: virtual time jumps deadline to deadline",
                },
                "speed": {"type": "number", "description": "virtual clock multiplier (--speed)"},
                "start": {
                    "type": "string",
                    "description": "virtual start time, e.g. '2027/10/6 18:30:00'",
                },
                "timeout": {
                    "type": "number",
                    "description": "wall-clock seconds before the run is killed (default 120)",
                },
            },
            "required": ["files"],
        },
        "handler": _qa_run,
    },
}
