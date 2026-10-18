"""The MCP tool registry: name, JSON-Schema input, handler.

V1 tools wrap what flua already ships — one-shot semantics identical to the
CLI, so the tool results can never drift from the documented flags.
Sessions (qa_start/qa_probe/…) come later on the in-process engine
(notes-mcp.md). Handlers return plain JSON; the server wraps it in MCP
content blocks.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import threading
import time
from typing import Any

from ..check import check_file
from ..engine import LuaEngine
from ..tools.ui import ui_dump
from .jsonrpc import INTERNAL_ERROR, INVALID_PARAMS, JsonRpcError
from .resources import list_resources, read_resource
from .sessions import DEFAULT_TTL, SessionManager

Tool = dict[str, Any]

_SESSIONS = SessionManager()

# One-shot run tools (qa_run subprocesses, devices engines) share a run-slot
# cap: a host cannot make the server spawn unbounded processes/engines at
# once. Extra runs fail fast with isError — the agent retries. Sessions are
# a separate lifecycle (TTL-reaped), not covered here.
MAX_CONCURRENT_RUNS = 4
_RUN_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)


def _acquire_run_slot() -> None:
    if not _RUN_SLOTS.acquire(blocking=False):
        raise JsonRpcError(
            INTERNAL_ERROR,
            f"server busy: {MAX_CONCURRENT_RUNS} runs already in flight (the cap); retry shortly",
        )


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
    systemEvents / refreshStates since the last probe (cursor deltas)."""
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


def _devices(args: dict[str, Any]) -> dict[str, Any]:
    """Run QA files to completion (one-shot, like qa_run) and return the
    final device list from the REST feeds — the simulated house after the
    run — plus the aggregated exit code."""
    mode = args.get("mode")
    if mode not in (None, "local", "remote"):
        raise JsonRpcError(INVALID_PARAMS, "mode must be 'local' or 'remote'")
    timeout = args.get("timeout")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise JsonRpcError(INVALID_PARAMS, "timeout must be a positive number of seconds")
    loop = asyncio.new_event_loop()
    _acquire_run_slot()
    try:
        engine = LuaEngine(
            api_mode="local" if mode is None else mode,
            speed=float("inf")
            if args.get("instant")
            else (args.get("speed") if args.get("speed") is not None else 1.0),
            start=_parse_start(args.get("start")),
            log_stream=sys.stderr,  # stdout stays pure JSON-RPC on the stdio transport
        )
        max_hours = args.get("maxHours")
        if max_hours is not None:
            if not isinstance(max_hours, (int, float)) or max_hours <= 0:
                raise JsonRpcError(
                    INVALID_PARAMS, "maxHours must be a positive number of virtual hours"
                )
            engine.limit_run(float(max_hours) * 3600.0)
        exit_code = loop.run_until_complete(
            _drain_engine(
                engine, _file_list(args), float(timeout if timeout is not None else 120.0)
            )
        )
        devices, status = engine.api.dispatch("GET", "/devices")
        return {"exitCode": exit_code, "devices": devices if status == 200 else None}
    except ValueError as exc:
        raise JsonRpcError(INVALID_PARAMS, str(exc)) from None
    finally:
        _RUN_SLOTS.release()
        loop.close()


async def _drain_engine(engine: LuaEngine, files: list[str], timeout: float) -> int:
    """Start the QAs and pump until nothing is pending (or the wall-clock
    timeout); returns the aggregated exit code."""
    await engine.start()
    try:
        for path in files:
            qa_id, error = engine.load_qa_file(path)  # CLI-parity: --%% directives
            if error is not None:
                raise JsonRpcError(INVALID_PARAMS, f"{path}: {error}")
            assert qa_id is not None
        deadline = time.monotonic() + timeout
        while engine.has_pending_work() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if engine.has_pending_work():
            raise JsonRpcError(INTERNAL_ERROR, f"run timed out after {timeout}s")
        return engine.exit_code
    finally:
        await engine.stop()


def _docs_list(args: dict[str, Any]) -> dict[str, Any]:
    """The docs tree as a tool: the same listing resources/list serves, for
    hosts whose MCP client only exposes tools (see the dogfood note in
    notes-mcp.md)."""
    return {"docs": list_resources({})["resources"]}


def _docs_read(args: dict[str, Any]) -> dict[str, Any]:
    """Read one doc: the same tree resources/read serves. Accepts both
    "USAGE.md" and "flua://docs/USAGE.md"."""
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        raise JsonRpcError(INVALID_PARAMS, "path (string) is required — see docs_list")
    uri = path.strip()
    if not uri.startswith("flua://docs/"):
        uri = "flua://docs/" + uri.lstrip("/")
    try:
        result = read_resource({"uri": uri})
    except JsonRpcError as exc:
        raise JsonRpcError(
            INVALID_PARAMS, f"{exc.message} — docs_list lists the available docs"
        ) from None
    return {"path": uri[len("flua://docs/") :], "text": result["contents"][0]["text"]}


def _session_for(args: dict[str, Any]) -> Any:
    session_id = args.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise JsonRpcError(INVALID_PARAMS, "sessionId (string) is required")
    try:
        return _SESSIONS.get(session_id)
    except KeyError:
        raise JsonRpcError(
            INVALID_PARAMS,
            f"unknown session: {session_id} — it may have expired (ttl); "
            "qa_sessions lists the live sessions",
        ) from None


def _qa_run(args: dict[str, Any]) -> dict[str, Any]:
    """Run QA files to completion (the offline sim by default) and return
    the exit code, the JSON log lines, and the stderr verdict lines."""
    mode = args.get("mode")
    if mode not in (None, "local", "remote"):
        raise JsonRpcError(INVALID_PARAMS, "mode must be 'local' or 'remote'")
    timeout = args.get("timeout")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise JsonRpcError(INVALID_PARAMS, "timeout must be a positive number of seconds")
    max_hours = args.get("maxHours")
    if max_hours is not None and (not isinstance(max_hours, (int, float)) or max_hours <= 0):
        raise JsonRpcError(INVALID_PARAMS, "maxHours must be a positive number of virtual hours")
    command = [sys.executable, "-m", "flua", "--log", "json"]
    if mode is not None:
        command += ["--api", mode]
    if args.get("instant"):
        command.append("--instant")
    if args.get("speed") is not None:
        command += ["--speed", str(args["speed"])]
    if args.get("start") is not None:
        command += ["--start", str(args["start"])]
    if max_hours is not None:
        command += ["--max-hours", str(max_hours)]
    command += _file_list(args)
    _acquire_run_slot()
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
    finally:
        _RUN_SLOTS.release()
    logs: list[Any] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            logs.append(json.loads(line))
        except ValueError:
            logs.append(line)  # never drop a line over a formatting surprise
    summary = _summarize(logs)
    filt = args.get("filter")
    if filt is not None:
        logs = _filter_logs(logs, filt)
    return {
        "exitCode": result.returncode,
        "logs": logs,
        "verdict": [line for line in result.stderr.splitlines() if line.strip()],
        "summary": summary,
    }


def _summarize(logs: list[Any]) -> dict[str, Any]:
    """The answer the agent wants without shelling out to jq: level counts,
    flua-test PASS/FAIL tallies, and the failures:N total."""
    levels: dict[str, int] = {}
    passed = failed = failures_total = 0
    for entry in logs:
        if not isinstance(entry, dict):
            continue
        level = str(entry.get("level") or "").upper()
        if level:
            levels[level] = levels.get(level, 0) + 1
        msg = str(entry.get("msg") or "")
        if msg.startswith("PASS:"):
            passed += 1
        elif msg.startswith("FAIL:"):
            failed += 1
        elif msg.startswith("failures: "):
            try:
                failures_total = max(failures_total, int(msg.split(":", 1)[1].strip()))
            except ValueError:
                pass
    return {"levels": levels, "pass": passed, "fail": failed, "failures": failures_total}


def _filter_logs(logs: list[Any], filt: dict[str, Any]) -> list[Any]:
    """Server-side log narrowing ({levels?, match?}) — the agent asks the
    server for 'just the failures' instead of shelling out to jq."""
    if not isinstance(filt, dict):
        raise JsonRpcError(INVALID_PARAMS, "filter must be an object {levels?, match?}")
    levels = filt.get("levels")
    if levels is not None:
        if not isinstance(levels, list) or not all(isinstance(name, str) for name in levels):
            raise JsonRpcError(INVALID_PARAMS, "filter.levels must be a list of level names")
        wanted = {name.upper() for name in levels}
        logs = [
            entry
            for entry in logs
            if isinstance(entry, dict) and str(entry.get("level") or "").upper() in wanted
        ]
    match = filt.get("match")
    if match is not None:
        if not isinstance(match, str):
            raise JsonRpcError(INVALID_PARAMS, "filter.match must be a string (regex)")
        try:
            pattern = re.compile(match)
        except re.error as exc:
            raise JsonRpcError(
                INVALID_PARAMS, f"filter.match is not a valid regex: {exc}"
            ) from None
        logs = [
            entry
            for entry in logs
            if pattern.search(entry.get("msg", "") if isinstance(entry, dict) else str(entry))
        ]
    return logs


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
            "Returns {exitCode, logs, verdict, summary}: logs are the QA's "
            "--log json lines, verdict the stderr notices, summary the "
            "level counts and flua-test PASS/FAIL tallies (no jq needed). "
            "`filter` narrows the returned logs server-side. One-shot — the run "
            "ends when the QAs drain; interactive probing is the session tools."
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
                "maxHours": {
                    "type": "number",
                    "description": (
                        "cap virtual time at N virtual hours (--max-hours): "
                        "timers beyond the horizon never fire"
                    ),
                },
                "timeout": {
                    "type": "number",
                    "description": "wall-clock seconds before the run is killed (default 120)",
                },
                "filter": {
                    "type": "object",
                    "properties": {
                        "levels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "keep only these log levels (e.g. [\"ERROR\", \"WARNING\"])"
                            ),
                        },
                        "match": {
                            "type": "string",
                            "description": (
                                "regex matched against the log message (e.g. \"FAIL|Schedule:\")"
                            ),
                        },
                    },
                    "description": (
                        "narrow the returned logs server-side; the summary always "
                        "describes the whole run"
                    ),
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
    "devices": {
        "description": (
            "Run QA files to completion (one-shot, like qa_run) and return the "
            "final device list from the REST feeds — [{id, name, type, "
            "properties, ...}] — the simulated house after the run, plus the "
            "aggregated exitCode. Offline by default; instant=true collapses "
            "virtual time."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "QA files to run",
                },
                "mode": {"type": "string", "enum": ["local", "remote"]},
                "instant": {"type": "boolean"},
                "speed": {"type": "number"},
                "start": {"type": "string", "description": "virtual start time"},
                "maxHours": {
                    "type": "number",
                    "description": (
                        "cap virtual time at N virtual hours (--max-hours): "
                        "timers beyond the horizon never fire"
                    ),
                },
                "timeout": {
                    "type": "number",
                    "description": "wall seconds (default 120)",
                },
            },
            "required": ["files"],
        },
        "handler": _devices,
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
            "Probe a session: {devices, qas, debugMessages, systemEvents, "
            "refreshStates} — the three feeds are deltas since the previous "
            "probe (cursor-based), so repeated probes only show what is new. "
            "refreshStates carries the HC3 polling shape "
            "{status, last, changes, events}."
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
    "docs_list": {
        "description": (
            "List the flua documentation that ships with this server: "
            "[{uri, name, title, description, mimeType}] — USAGE.md (QA "
            "directives incl. --%%file multi-file rules, network, deploy), "
            "ARCHITECTURE.md, the tutorial chapters (09/10: multi-file QAs "
            "and debugging), mcp.md (this server), specs/hc3-api.json. "
            "Read them with docs_read instead of searching the web."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": _docs_list,
    },
    "docs_read": {
        "description": (
            "Read one flua doc by path (e.g. 'USAGE.md', "
            "'tutorial/09-multi-file-qas.md', 'flua://docs/mcp.md') and "
            "return its full text. The docs ship in the wheel — this is the "
            "authoritative local reference, no web search needed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "the doc path, with or without the flua://docs/ prefix",
                },
            },
            "required": ["path"],
        },
        "handler": _docs_read,
    },
}
