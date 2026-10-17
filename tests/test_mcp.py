"""flua-mcp: the JSON-RPC core, the stdio transport, and the V1 tools.

In-process tests drive the dispatch function directly; the end-to-end test
spawns ``python -m flua.mcp.server`` and speaks JSON-RPC over stdio.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.mcp import jsonrpc as core  # noqa: E402
from flua.mcp.server import (  # noqa: E402
    LEGACY_PROTOCOL_VERSION,
    METHODS,
    SUPPORTED_VERSIONS,
    _check_protocol_version,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _dispatch(line: str) -> dict | None:
    # the same precheck run_stdio installs: per-request protocol version
    return core.handle_message(line, METHODS, precheck=_check_protocol_version)


def _call(name: str, args: dict) -> dict:
    response = _dispatch(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": name, "params": args})
    )
    assert response is not None and "error" not in response, response
    return response["result"]


def _tool(name: str, args: dict) -> dict:
    """Call a tool through tools/call; returns the parsed JSON result, or
    {isError: True, message} for tool-level failures."""
    result = _call("tools/call", {"name": name, "arguments": args})
    if result["isError"]:
        return {"isError": True, "message": result["content"][0]["text"]}
    return json.loads(result["content"][0]["text"])


# -- JSON-RPC core --------------------------------------------------------------


def test_parse_error_answers_with_id_null() -> None:
    response = _dispatch("{not json")
    assert response is not None
    assert response["error"]["code"] == core.PARSE_ERROR
    assert response["id"] is None


def test_invalid_request() -> None:
    response = _dispatch(json.dumps({"jsonrpc": "1.0", "id": 1, "method": "ping"}))
    assert response is not None
    assert response["error"]["code"] == core.INVALID_REQUEST


def test_method_not_found() -> None:
    response = _dispatch(json.dumps({"jsonrpc": "2.0", "id": 7, "method": "nope"}))
    assert response is not None
    assert response["error"]["code"] == core.METHOD_NOT_FOUND
    assert response["id"] == 7


def test_notifications_get_no_response() -> None:
    response = _dispatch(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    assert response is None


# -- MCP surface -----------------------------------------------------------------


def test_initialize_handshake() -> None:
    # the legacy (initialize-era) handshake: still served for older clients
    result = _call("initialize", {"protocolVersion": LEGACY_PROTOCOL_VERSION})
    assert result["protocolVersion"] == LEGACY_PROTOCOL_VERSION
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"]["name"] == "flua-mcp"


def test_discover_lists_supported_versions() -> None:
    # server/discover (2026-07-28, required): versions, capabilities, identity
    result = _call("server/discover", {})
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == SUPPORTED_VERSIONS
    assert "2026-07-28" in result["supportedVersions"]
    assert result["capabilities"] == {"tools": {}}
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "flua-mcp"
    assert result["instructions"]


def test_modern_per_request_version_check() -> None:
    # 2026-07-28: the version rides params._meta per request; a supported
    # version is served, an unknown one answers -32022 with the list
    response = _dispatch(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
                "params": {
                    "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
                },
            }
        )
    )
    assert response is not None and response["result"] == {}
    response = _dispatch(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "ping",
                "params": {
                    "_meta": {"io.modelcontextprotocol/protocolVersion": "1900-01-01"}
                },
            }
        )
    )
    assert response is not None
    assert response["error"]["code"] == -32022
    assert response["error"]["data"] == {
        "supported": SUPPORTED_VERSIONS,
        "requested": "1900-01-01",
    }


def test_tools_list_shape() -> None:
    result = _call("tools/list", {})
    assert result["resultType"] == "complete"
    names = [t["name"] for t in result["tools"]]
    assert names == ["qa_check", "qa_run"]
    for tool in result["tools"]:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"]["required"] == ["files"]


def test_unknown_tool_is_an_rpc_error() -> None:
    # per the MCP spec, tools/call for an unknown tool is a JSON-RPC error
    response = _dispatch(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "nope", "arguments": {}},
            }
        )
    )
    assert response is not None
    assert response["error"]["code"] == core.METHOD_NOT_FOUND
    assert "unknown tool" in response["error"]["message"]


# -- qa_check --------------------------------------------------------------------


def test_qa_check_clean_file(tmp_path) -> None:
    script = tmp_path / "good.lua"
    script.write_text("--%%name:x\nprint('hi')\n")
    result = _tool("qa_check", {"files": [str(script)]})
    assert result == {"ok": True, "findings": []}


def test_qa_check_reports_syntax_and_includes(tmp_path) -> None:
    main = tmp_path / "main.lua"
    lib = tmp_path / "lib.lua"
    main.write_text("--%%name:x\n--%%file:lib.lua,lib\nprint(LIB)\n")
    lib.write_text("LIB = )\n")
    result = _tool("qa_check", {"files": [str(main)]})
    assert result["ok"] is False
    severities = {f["severity"] for f in result["findings"]}
    assert "error" in severities
    assert any(str(lib) in f["file"] for f in result["findings"])


def test_qa_check_bad_args() -> None:
    result = _tool("qa_check", {"files": []})
    assert result["isError"] is True


# -- qa_run ----------------------------------------------------------------------


def test_qa_run_returns_exit_logs_and_verdict(tmp_path) -> None:
    script = tmp_path / "run.lua"
    script.write_text("print('hello agent')\nexit(0)\n")
    result = _tool("qa_run", {"files": [str(script)]})
    assert result["exitCode"] == 0
    assert any(
        isinstance(line, dict) and line.get("msg") == "hello agent" for line in result["logs"]
    )
    assert result["verdict"] == []


def test_qa_run_failing_qa_sets_exit_code(tmp_path) -> None:
    script = tmp_path / "fail.lua"
    script.write_text("exit(7)\n")
    result = _tool("qa_run", {"files": [str(script)]})
    assert result["exitCode"] == 7
    assert any("exited with code 7" in line for line in result["verdict"])


def test_qa_run_instant(tmp_path) -> None:
    script = tmp_path / "instant.lua"
    script.write_text(
        "--%%name:fast\nsetTimeout(function() print('LATER') end, 60 * 1000)\n"
    )
    result = _tool("qa_run", {"files": [str(script)], "instant": True})
    assert result["exitCode"] == 0
    assert any(
        isinstance(line, dict) and line.get("msg") == "LATER" for line in result["logs"]
    )


def test_qa_run_bad_mode() -> None:
    result = _tool("qa_run", {"files": ["x.lua"], "mode": "banana"})
    assert result["isError"] is True


# -- end-to-end over stdio ---------------------------------------------------------


def test_stdio_transport_end_to_end(tmp_path) -> None:
    script = tmp_path / "e2e.lua"
    script.write_text("print('E2E')\nexit(0)\n")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
                "name": "qa_run",
                "arguments": {"files": [str(script)]},
            },
        },
        {"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {}},
    ]
    process = subprocess.run(
        [sys.executable, "-m", "flua.mcp.server"],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr
    responses = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    # one response per request; the notification is silent
    assert [r["id"] for r in responses] == [1, 2, 3, 4, 5]
    assert "2026-07-28" in responses[0]["result"]["supportedVersions"]
    assert responses[1]["result"]["protocolVersion"] == LEGACY_PROTOCOL_VERSION
    assert [t["name"] for t in responses[2]["result"]["tools"]] == ["qa_check", "qa_run"]
    run_result = json.loads(responses[3]["result"]["content"][0]["text"])
    assert run_result["exitCode"] == 0
    assert responses[4]["result"] == {}
