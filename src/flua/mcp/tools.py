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
from ..tools.ui import ui_dump
from .jsonrpc import INTERNAL_ERROR, INVALID_PARAMS, JsonRpcError
from .sessions import DEFAULT_TTL, SessionManager

Tool = dict[str, Any]

_SESSIONS = SessionManager()


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


def _qa_ui(args: dict[str, Any]) -> dict[str, Any]:
    """The structured UI of one QA (the --tool ui --json payload)."""
    files = _file_list(args)
    if len(files) != 1:
        raise JsonRpcError(INVALID_PARAMS, "qa_ui takes exactly one file")
    try:
        return ui_dump(files[0])
    except (FileNotFoundError, ValueError) as exc:
        raise JsonRpcError(INVALID_PARAMS, str(exc)) from None


def _qa_start(args: dict[str, Any]) -> dict[str, Any]:
    """Start a session: a running engine with the given QAs. Returns
    {sessionId, qaIds}; the id is an explicit argument on every later
    session tool (the transport itself stays stateless)."""
    mode = args.get("mode")
    if mode not in (None, "local", "remote"):
        raise JsonRpcError(INVALID_PARAMS, "mode must be 'local' or 'remote'")
    ttl = args.get("ttl", DEFAULT_TTL)
    if not isinstance(ttl, (int, float)) or ttl <= 0:
        raise JsonRpcError(INVALID_PARAMS, "ttl must be a positive number of seconds")
    try:
        return _SESSIONS.start(
            _file_list(args),
            mode,
            bool(args.get("instant")),
            args.get("speed"),
            _parse_start(args.get("start")),
            float(ttl),
        )
    except (ValueError, RuntimeError) as exc:
        raise JsonRpcError(INTERNAL_ERROR, str(exc)) from None


def _parse_start(raw: Any) -> float | None:
    if raw is None:
        return None
    from ..clock import parse_start_time

    try:
        return parse_start_time(str(raw))
    except ValueError as exc:
        raise JsonRpcError(INVALID_PARAMS, str(exc)) from None


def _qa_probe(args: dict[str, Any]) -> dict[str, Any]:
    """Probe a session: devices, QA status, and the new debugMessages /
    systemEvents since the last probe (cursor-based deltas)."""
    session = _session_for(args)
    return _SESSIONS.probe(session)


def _qa_action(args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a device action into a running session's QA (callAction)."""
    session = _session_for(args)
    qa_id = args.get("qaId")
    action = args.get("action")
    if not isinstance(qa_id, int) or not isinstance(action, str) or not action:
        raise JsonRpcError(INVALID_PARAMS, "qaId (int) and action (string) are required")
    args_list = args.get("args")
    if args_list is None:
        args_list = []
    if not isinstance(args_list, list):
        raise JsonRpcError(INVALID_PARAMS, "args must be a list")
    return _SESSIONS.action(session, qa_id, action, args_list)


def _qa_stop(args: dict[str, Any]) -> dict[str, Any]:
    return {"stopped": _SESSIONS.stop(str(args.get("sessionId") or ""))}


def _qa_sessions(args: dict[str, Any]) -> dict[str, Any]:
    return {"sessions": _SESSIONS.list()}


def _session_for(args: dict[str, Any]) -> Any:
    session_id = args.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise JsonRpcError(INVALID_PARAMS, "sessionId (string) is required")
    try:
        return _SESSIONS.get(session_id)
    except KeyError:
        raise JsonRpcError(INVALID_PARAMS, f"unknown session: {session_id}") from None


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
    "qa_ui": {
        "description": (
            "The structured UI of one QA: {name, type, useUiView, elements, "
            "callbacks} — elements carry their name/text/value/options, the same "
            "payload as `flua --tool ui --json`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 1,
                    "description": "the QA file (exactly one)",
                },
            },
            "required": ["files"],
        },
        "handler": _qa_ui,
    },
    "qa_start": {
        "description": (
            "Start a session: a running flua engine with the given QAs, kept "
            "alive for probing. Returns {sessionId, qaIds} — the sessionId is an "
            "explicit argument on every session tool. Sessions idle out after "
            "`ttl` seconds (default 600)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "QA files to load into the session",
                },
                "mode": {"type": "string", "enum": ["local", "remote"]},
                "instant": {"type": "boolean"},
                "speed": {"type": "number"},
                "start": {"type": "string", "description": "virtual start time"},
                "ttl": {
                    "type": "number",
                    "description": "idle seconds before auto-stop (default 600)",
                },
            },
            "required": ["files"],
        },
        "handler": _qa_start,
    },
    "qa_probe": {
        "description": (
            "Probe a session: {devices, qas, debugMessages, systemEvents} — the "
            "two log feeds are deltas since the previous probe (cursor-based), so "
            "repeated probes only show what is new."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sessionId": {"type": "string", "description": "from qa_start"},
            },
            "required": ["sessionId"],
        },
        "handler": _qa_probe,
    },
    "qa_action": {
        "description": (
            "Dispatch a device action into a running session's QA (the HC3's "
            "POST /devices/{id}/action/{action} — reaches the QA's callAction). "
            "Returns {status}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sessionId": {"type": "string"},
                "qaId": {"type": "integer"},
                "action": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["sessionId", "qaId", "action"],
        },
        "handler": _qa_action,
    },
    "qa_stop": {
        "description": "Stop a session (tears the engine down). Returns {stopped}.",
        "inputSchema": {
            "type": "object",
            "properties": {"sessionId": {"type": "string"}},
            "required": ["sessionId"],
        },
        "handler": _qa_stop,
    },
    "qa_sessions": {
        "description": "List the live sessions: [{sessionId, qaIds, ageSeconds}].",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": _qa_sessions,
    },
}
