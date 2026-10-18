"""flua-mcp: the JSON-RPC core, the stdio transport, and the V1 tools.

In-process tests drive the dispatch function directly; the end-to-end test
spawns ``python -m flua.mcp.server`` and speaks JSON-RPC over stdio.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.mcp import jsonrpc as core  # noqa: E402
from flua.mcp import tools as mcp_tools  # noqa: E402
from flua.mcp.server import (  # noqa: E402
    LEGACY_PROTOCOL_VERSION,
    METHODS,
    SUPPORTED_VERSIONS,
    _check_protocol_version,
)
from flua.mcp.tools import MAX_CONCURRENT_RUNS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_sessions():
    # the session manager is a module singleton: never leak an engine into
    # the next test, even when a test fails mid-way
    yield
    from flua.mcp.tools import _SESSIONS

    _SESSIONS.shutdown()


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
    assert result["capabilities"] == {"tools": {}, "resources": {}, "prompts": {}}
    assert result["serverInfo"]["name"] == "flua-mcp"


def test_discover_lists_supported_versions() -> None:
    # server/discover (2026-07-28, required): versions, capabilities, identity
    result = _call("server/discover", {})
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == SUPPORTED_VERSIONS
    assert "2026-07-28" in result["supportedVersions"]
    assert result["capabilities"] == {"tools": {}, "resources": {}, "prompts": {}}
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "flua-mcp"
    assert result["instructions"]
    # the instructions are the discovery hook for the knowledge tiers:
    # they must steer agents at docs/prompts, not at web search
    assert "docs_list" in result["instructions"]
    assert "flua://docs/USAGE.md" in result["instructions"]
    assert "qa_probe" in result["instructions"]


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
    assert names == [
        "qa_check",
        "qa_run",
        "qa_ui",
        "devices",
        "qa_start",
        "qa_probe",
        "qa_action",
        "qa_stop",
        "qa_sessions",
        "docs_list",
        "docs_read",
    ]
    for tool in result["tools"]:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


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


# -- resources ------------------------------------------------------------------


def test_resources_list_serves_the_packaged_docs() -> None:
    result = _call("resources/list", {})
    assert result["resultType"] == "complete"
    uris = [r["uri"] for r in result["resources"]]
    assert "flua://docs/USAGE.md" in uris
    assert "flua://docs/mcp.md" in uris
    assert "flua://docs/tutorial/01-install.md" in uris
    usage = next(r for r in result["resources"] if r["uri"] == "flua://docs/USAGE.md")
    assert usage["mimeType"] == "text/markdown"
    assert usage["description"]
    # binary files (the tutorial PDF) stay out of the resource list
    assert not any(r["uri"].endswith(".pdf") for r in result["resources"])


def test_resources_read_returns_doc_content() -> None:
    result = _call("resources/read", {"uri": "flua://docs/USAGE.md"})
    assert result["resultType"] == "complete"
    assert result["contents"][0]["uri"] == "flua://docs/USAGE.md"
    assert result["contents"][0]["mimeType"] == "text/markdown"
    packaged = REPO_ROOT / "src" / "flua" / "setup_templates" / "docs" / "USAGE.md"
    assert result["contents"][0]["text"] == packaged.read_text(encoding="utf-8")


def test_resources_reject_traversal_and_unknown() -> None:
    # .. must not escape the docs tree, encoded or not
    for uri in (
        "flua://docs/../pyproject.toml",
        "flua://docs/%2e%2e/pyproject.toml",
        "flua://docs/..%2fpyproject.toml",
    ):
        response = _dispatch(
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": uri}}
            )
        )
        assert response is not None
        assert response["error"]["code"] == core.INVALID_PARAMS, uri
    # unknown files and non-text targets are clean errors, not crashes
    for uri in ("flua://docs/nope.md", "flua://docs/tutorial/flua-tutorial.pdf"):
        response = _dispatch(
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": uri}}
            )
        )
        assert response is not None
        assert response["error"]["code"] == core.INVALID_PARAMS, uri


def test_resources_read_suggests_close_matches() -> None:
    # agents guess doc paths; the error must name the right one (dogfood:
    # 'tutorial/10-debugging-the-ensemble.md' -> '10-multi-qa-debugging.md')
    response = _dispatch(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {"uri": "flua://docs/tutorial/10-debugging-the-ensemble.md"},
            }
        )
    )
    assert response is not None
    assert "did you mean" in response["error"]["message"]
    assert "tutorial/10-multi-qa-debugging.md" in response["error"]["message"]


def test_resources_read_rejects_non_docs_uri() -> None:
    response = _dispatch(
        json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": "file:///etc/passwd"}}
        )
    )
    assert response is not None
    assert response["error"]["code"] == core.INVALID_PARAMS


# -- prompts --------------------------------------------------------------------


def test_prompts_list_shape() -> None:
    result = _call("prompts/list", {})
    assert result["resultType"] == "complete"
    assert [p["name"] for p in result["prompts"]] == ["qa_debug", "qa_skeleton"]
    debug = next(p for p in result["prompts"] if p["name"] == "qa_debug")
    assert debug["title"] and debug["description"]
    assert [a["name"] for a in debug["arguments"] if a["required"]] == ["error"]
    skeleton = next(p for p in result["prompts"] if p["name"] == "qa_skeleton")
    assert [a["name"] for a in skeleton["arguments"]] == ["name"]
    assert skeleton["arguments"][0].get("required") is not True


def test_prompt_get_qa_debug_binds_error_and_code() -> None:
    result = _call(
        "prompts/get",
        {"name": "qa_debug", "arguments": {"error": "BOOM", "code": "print('x'"}},
    )
    assert result["resultType"] == "complete"
    message = result["messages"][0]
    assert message["role"] == "user"
    assert message["content"]["type"] == "text"
    assert "BOOM" in message["content"]["text"]
    assert "print('x'" in message["content"]["text"]
    # guidance points at the docs resources
    assert "flua://docs/invariants.md" in message["content"]["text"]


def test_prompt_get_qa_debug_requires_error() -> None:
    response = _dispatch(
        json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": {"name": "qa_debug"}}
        )
    )
    assert response is not None
    assert response["error"]["code"] == core.INVALID_PARAMS
    assert "error" in response["error"]["message"]


def test_prompt_get_unknown_prompt_is_an_error() -> None:
    response = _dispatch(
        json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": {"name": "nope"}}
        )
    )
    assert response is not None
    assert response["error"]["code"] == core.METHOD_NOT_FOUND


def test_qa_skeleton_substitutes_name_and_stays_runnable(tmp_path) -> None:
    result = _call("prompts/get", {"name": "qa_skeleton", "arguments": {"name": "kitchen-lamp"}})
    text = result["messages"][0]["content"]["text"]
    assert "--%%name:kitchen-lamp" in text
    assert "__NAME__" not in text
    # the shipped skeleton must actually run: extract the lua block and
    # drive it through the real qa_run tool
    import re as _re

    block = _re.search(r"```lua\n(.*?)\n```", text, _re.DOTALL)
    assert block, "no lua block in the skeleton prompt"
    script = tmp_path / "kitchen-lamp.lua"
    script.write_text(block.group(1))
    run = _tool("qa_run", {"files": [str(script)], "instant": True})
    assert run["exitCode"] == 0, run["logs"]
    assert run["summary"]["failures"] == 0


def test_docs_tools_serve_the_same_tree_as_resources() -> None:
    # hosts whose MCP client only exposes tools (Copilot) get the docs tree
    # as tools — the same content resources/read serves
    listed = _tool("docs_list", {})
    assert any(d["uri"] == "flua://docs/USAGE.md" for d in listed["docs"])
    read = _tool("docs_read", {"path": "USAGE.md"})
    assert read["path"] == "USAGE.md"
    assert "--%%file" in read["text"]
    # the flua://docs/ prefix form resolves to the same doc
    via_uri = _tool("docs_read", {"path": "flua://docs/tutorial/09-multi-file-qas.md"})
    assert "--%%file" in via_uri["text"]


def test_docs_read_unknown_path_points_at_docs_list() -> None:
    result = _tool("docs_read", {"path": "tutorial/01-first-qa.md"})
    assert result["isError"] is True
    assert "docs_list" in result["message"]
    # the close-match hint names the real chapter
    assert "tutorial/02-your-first-qa.md" in result["message"]


def test_docs_read_rejects_traversal() -> None:
    result = _tool("docs_read", {"path": "../pyproject.toml"})
    assert result["isError"] is True
    assert "escapes" in result["message"] or "no such resource" in result["message"]


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


def test_qa_run_summary_counts_assertions_and_levels(tmp_path) -> None:
    # the summary answers "how did it go" without shelling out to jq:
    # level counts, flua-test PASS/FAIL tallies, and the failures total
    script = tmp_path / "sum.lua"
    script.write_text(
        "local Test = require('flua-test')\n"
        "local t = Test.new()\n"
        "t:expect(true, 'one is one')\n"
        "t:expect(true, 'two is two')\n"
        "t:expect(false, 'nope')\n"
        "fibaro.warning(__TAG, 'watch out')\n"
        "t:finish()\n"
    )
    result = _tool("qa_run", {"files": [str(script)]})
    assert result["summary"]["pass"] == 2
    assert result["summary"]["fail"] == 1
    assert result["summary"]["failures"] == 1
    assert result["summary"]["levels"].get("WARNING", 0) >= 1
    assert result["exitCode"] == 1


def test_qa_run_filter_narrows_logs_server_side(tmp_path) -> None:
    script = tmp_path / "flt.lua"
    script.write_text(
        "print('TICK one')\n"
        "print('TICK two')\n"
        "fibaro.error(__TAG, 'boom')\n"
        "exit(0)\n"
    )
    result = _tool("qa_run", {"files": [str(script)], "filter": {"levels": ["ERROR"]}})
    assert any("boom" in (e.get("msg") or "") for e in result["logs"] if isinstance(e, dict))
    assert all(
        (e.get("level") or "").upper() == "ERROR" for e in result["logs"] if isinstance(e, dict)
    )
    # the summary still describes the whole run, not the filtered view
    assert result["summary"]["levels"].get("DEBUG", 0) >= 2
    result = _tool("qa_run", {"files": [str(script)], "filter": {"match": "TICK two"}})
    assert any("TICK two" in (e.get("msg") or "") for e in result["logs"] if isinstance(e, dict))
    assert not any(
        "TICK one" in (e.get("msg") or "") for e in result["logs"] if isinstance(e, dict)
    )


def test_qa_run_bad_filter_regex() -> None:
    result = _tool("qa_run", {"files": ["x.lua"], "filter": {"match": "("}})
    assert result["isError"] is True


# -- devices ----------------------------------------------------------------------


def test_devices_returns_the_final_house_state(tmp_path) -> None:
    script = tmp_path / "dev.lua"
    script.write_text(
        "--%%name:dev_probe\n"
        "function QuickApp:onInit()\n"
        "  self:updateProperty('value', 42)\n"
        "  exit(0)\n"
        "end\n"
    )
    result = _tool("devices", {"files": [str(script)], "instant": True})
    assert result["exitCode"] == 0
    # the list holds the HC3 pseudo-device (id 1) and the QA itself
    qa = next(d for d in result["devices"] if d["id"] == 5000)
    assert qa["name"] == "dev_probe"
    assert qa["properties"]["value"] == 42


def test_devices_reports_the_exit_code(tmp_path) -> None:
    script = tmp_path / "dev_fail.lua"
    script.write_text("print('nope')\nexit(3)\n")
    result = _tool("devices", {"files": [str(script)], "instant": True})
    assert result["exitCode"] == 3
    assert result["devices"]  # the exited QA is still listed


def test_devices_rejects_bad_mode() -> None:
    result = _tool("devices", {"files": ["x.lua"], "mode": "cloud"})
    assert result["isError"] is True
    assert "mode" in result["message"]


def test_devices_times_out_on_a_qa_that_never_drains(tmp_path) -> None:
    script = tmp_path / "dev_forever.lua"
    script.write_text("setTimeout(function() print('late') end, 3600000)\n")
    result = _tool("devices", {"files": [str(script)], "timeout": 0.5})
    assert result["isError"] is True
    assert "timed out" in result["message"]


# -- run-slot cap ------------------------------------------------------------------


def test_run_tools_fail_fast_when_the_cap_is_exhausted(tmp_path, monkeypatch) -> None:
    # a fully exhausted semaphore: qa_run and devices both answer busy,
    # never queue — the cap is shared and fail-fast
    script = tmp_path / "quick.lua"
    script.write_text("print('hi')\nexit(0)\n")
    exhausted = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
    for _ in range(MAX_CONCURRENT_RUNS):
        exhausted.acquire()
    monkeypatch.setattr(mcp_tools, "_RUN_SLOTS", exhausted)
    for tool in ("qa_run", "devices"):
        result = _tool(tool, {"files": [str(script)]})
        assert result["isError"] is True
        assert "busy" in result["message"]


@pytest.mark.slow
def test_qa_run_caps_concurrent_subprocesses(tmp_path) -> None:
    # MAX_CONCURRENT_RUNS real qa_run subprocesses hold the slots (a 2s
    # realtime timer each); a further run answers busy, then everything
    # finishes cleanly
    script = tmp_path / "hold.lua"
    script.write_text("setTimeout(function() exit(0) end, 2000)\n")
    results: list[dict | None] = [None] * MAX_CONCURRENT_RUNS
    barrier = threading.Barrier(MAX_CONCURRENT_RUNS)

    def run(index: int) -> None:
        barrier.wait()  # start together so all four are in flight
        results[index] = _tool("qa_run", {"files": [str(script)]})

    threads = [
        threading.Thread(target=run, args=(i,), daemon=True) for i in range(MAX_CONCURRENT_RUNS)
    ]
    for thread in threads:
        thread.start()
    time.sleep(0.8)  # the four subprocesses have booted and hold their slots
    busy = _tool("qa_run", {"files": [str(script)]})
    assert busy["isError"] is True
    assert "busy" in busy["message"]
    for thread in threads:
        thread.join(timeout=30)
    assert all(result is not None and result["exitCode"] == 0 for result in results)


# -- qa_ui -----------------------------------------------------------------------


def test_qa_ui_dumps_elements_and_callbacks(tmp_path) -> None:
    script = tmp_path / "ui.lua"
    script.write_text(
        "--%%name:uitool\n"
        '--%%u:{button="B1",text="Press me",onReleased="go"}\n'
        '--%%u:{select="sel1",text="Pick",value="11",options={{type="option",text="One",value="11"}}}\n'
        "-- --------------- EOH ---------------\n"
        "function QuickApp:go() end\n"
    )
    result = _tool("qa_ui", {"files": [str(script)]})
    assert result["name"] == "uitool"
    kinds = {e.get("name"): e for e in result["elements"]}
    assert kinds["B1"]["type"] == "button"
    assert kinds["sel1"]["values"] == ["11"]
    assert {"callback": "go", "eventType": "onReleased", "name": "B1"} in result["callbacks"]


# -- sessions ---------------------------------------------------------------------


def _ticking_qa(tmp_path, name: str = "tick") -> str:
    script = tmp_path / f"{name}.lua"
    script.write_text(
        f"--%%name:{name}\n"
        "setInterval(function() print('TICK') end, 50)\n"
    )
    return str(script)


def test_session_start_probe_action_stop(tmp_path) -> None:
    started = _tool("qa_start", {"files": [_ticking_qa(tmp_path)]})
    session_id = started["sessionId"]
    assert started["qaIds"] == [5000]
    # the interval prints land in the probe's debugMessages delta
    import time as _time

    _time.sleep(0.3)
    probe = _tool("qa_probe", {"sessionId": session_id})
    assert probe["qas"][0]["name"] == "tick"
    assert any(d["tag"] == "tick5000" for d in probe["debugMessages"])
    assert probe["devices"]
    # the second probe is a delta: only messages newer than the cursor
    import time as _time

    _time.sleep(0.2)
    probe2 = _tool("qa_probe", {"sessionId": session_id})
    assert probe2["debugMessages"]
    assert probe2["debugMessages"][0]["id"] > probe["debugMessages"][-1]["id"]
    # sessions list + stop
    listed = _tool("qa_sessions", {})
    assert any(s["sessionId"] == session_id for s in listed["sessions"])
    assert _tool("qa_stop", {"sessionId": session_id}) == {"stopped": True}
    assert _tool("qa_sessions", {})["sessions"] == []


def test_session_probe_includes_the_refreshstates_feed(tmp_path) -> None:
    script = tmp_path / "tick_prop.lua"
    script.write_text(
        "--%%name:tick_prop\n"
        "function QuickApp:onInit()\n"
        "  setTimeout(function()\n"
        "    self:updateProperty('value', 7)\n"
        "  end, 100)\n"
        "end\n"
    )
    started = _tool("qa_start", {"files": [str(script)]})
    session_id = started["sessionId"]
    try:
        import time as _time

        _time.sleep(0.4)  # let the 100ms timer fire
        probe = _tool("qa_probe", {"sessionId": session_id})
        feed = probe["refreshStates"]
        assert feed["last"] > 0
        assert any(e["type"] == "DevicePropertyUpdatedEvent" for e in feed.get("events", []))
        _time.sleep(0.2)
        probe2 = _tool("qa_probe", {"sessionId": session_id})
        # cursor delta: the second probe sees nothing new
        assert probe2["refreshStates"]["last"] >= feed["last"]
        assert not probe2["refreshStates"].get("events")
    finally:
        _tool("qa_stop", {"sessionId": session_id})


def test_session_action_reaches_callaction(tmp_path) -> None:
    script = tmp_path / "act.lua"
    script.write_text(
        "--%%name:act\n"
        "function QuickApp:toggle() print('TOGGLED') end\n"
    )
    started = _tool("qa_start", {"files": [str(script)]})
    session_id = started["sessionId"]
    try:
        result = _tool("qa_action", {"sessionId": session_id, "qaId": 5000, "action": "toggle"})
        assert result["status"] == 202
        import time as _time

        _time.sleep(0.2)
        probe = _tool("qa_probe", {"sessionId": session_id})
        assert any("TOGGLED" in (d.get("message") or "") for d in probe["debugMessages"])
    finally:
        _tool("qa_stop", {"sessionId": session_id})


def test_session_ttl_reaps_idle_sessions(tmp_path) -> None:
    started = _tool("qa_start", {"files": [_ticking_qa(tmp_path)], "ttl": 0.3})
    assert started["sessionId"]
    import time as _time

    _time.sleep(0.6)
    # the reap runs lazily on the next session operation
    assert _tool("qa_sessions", {})["sessions"] == []


def test_session_probe_revives_an_idle_past_ttl_session(tmp_path) -> None:
    # a probe IS usage: asking about an idle session must revive it, not
    # let the lazy reap kill it first (dogfood: qa_probe answered "unknown
    # session" right after qa_start because the ttl had elapsed)
    started = _tool("qa_start", {"files": [_ticking_qa(tmp_path)], "ttl": 0.3})
    session_id = started["sessionId"]
    import time as _time

    _time.sleep(0.6)
    try:
        probe = _tool("qa_probe", {"sessionId": session_id})
        assert probe["qas"][0]["name"] == "tick"
        assert any(s["sessionId"] == session_id for s in _tool("qa_sessions", {})["sessions"])
    finally:
        _tool("qa_stop", {"sessionId": session_id})


def test_session_unknown_id_errors() -> None:
    result = _tool("qa_probe", {"sessionId": "nope"})
    assert result["isError"] is True
    assert "unknown session" in result["message"]


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
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "resources/read",
            "params": {"uri": "flua://docs/rest-endpoints.md"},
        },
        {"jsonrpc": "2.0", "id": 6, "method": "ping", "params": {}},
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
    assert [r["id"] for r in responses] == [1, 2, 3, 4, 5, 6]
    assert "2026-07-28" in responses[0]["result"]["supportedVersions"]
    assert responses[1]["result"]["protocolVersion"] == LEGACY_PROTOCOL_VERSION
    assert [t["name"] for t in responses[2]["result"]["tools"]][:2] == ["qa_check", "qa_run"]
    run_result = json.loads(responses[3]["result"]["content"][0]["text"])
    assert run_result["exitCode"] == 0
    assert responses[4]["result"]["contents"][0]["uri"] == "flua://docs/rest-endpoints.md"
    assert responses[4]["result"]["contents"][0]["text"]
    assert responses[5]["result"] == {}


def test_stdio_ctrl_c_exits_cleanly(tmp_path) -> None:
    # Ctrl-C on stdio: one stderr line, exit 130, no traceback — even with
    # a live session the teardown must not leak a KeyboardInterrupt
    import signal as _signal

    script = tmp_path / "sig.lua"
    script.write_text("print('sig')\n")
    process = subprocess.Popen(
        [sys.executable, "-m", "flua.mcp.server"],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # a live session, so the interrupt tears an engine down too
    process.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "qa_start", "arguments": {"files": [str(script)]}},
            }
        )
        + "\n"
    )
    process.stdin.flush()
    response = json.loads(process.stdout.readline())
    assert "sessionId" in json.loads(response["result"]["content"][0]["text"])
    process.send_signal(_signal.SIGINT)
    _, stderr = process.communicate(timeout=15)
    assert process.returncode == 130
    assert "flua-mcp: interrupted" in stderr
    assert "Traceback" not in stderr
