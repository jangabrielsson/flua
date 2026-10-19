"""flua-mcp: the Streamable HTTP transport (stateless mode).

In-process tests drive a server on an ephemeral 127.0.0.1 port (never a
fixed port, never non-loopback); one test spawns the real CLI. No external
network anywhere.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.mcp.http import MAX_BODY_BYTES, StreamableHttpServer  # noqa: E402
from flua.mcp.server import METHODS, _check_protocol_version  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def http_server():
    started: list[StreamableHttpServer] = []

    def start(token: str | None = None) -> StreamableHttpServer:
        server = StreamableHttpServer(
            "127.0.0.1", 0, METHODS, _check_protocol_version, token=token
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.append(server)
        return server

    yield start
    for server in started:
        server.shutdown()
        server.server_close()


def _post(
    server: StreamableHttpServer,
    payload: object | bytes,
    token: str | None = None,
    headers: dict[str, str] | None = None,
    method: str = "POST",
    path: str = "/mcp",
) -> tuple[int, str]:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _rpc(method: str, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


# -- the transport -----------------------------------------------------------------


def test_http_discover_roundtrip(http_server) -> None:
    status, body = _post(http_server(), _rpc("server/discover"))
    assert status == 200
    result = json.loads(body)["result"]
    assert result["resultType"] == "complete"
    assert sorted(result["capabilities"]) == ["prompts", "resources", "tools"]


def test_http_runs_a_qa_end_to_end(http_server, tmp_path) -> None:
    script = tmp_path / "http-e2e.lua"
    script.write_text("print('HTTP_OK')\nexit(0)\n")
    status, body = _post(
        http_server(),
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
                "name": "qa_run",
                "arguments": {"files": [str(script)]},
            },
        },
    )
    assert status == 200
    result = json.loads(body)["result"]
    run = json.loads(result["content"][0]["text"])
    assert run["exitCode"] == 0
    assert any("HTTP_OK" in str(entry) for entry in run["logs"])


def test_http_reads_resources_and_prompts(http_server) -> None:
    server = http_server()
    status, body = _post(server, _rpc("resources/read", {"uri": "flua://docs/USAGE.md"}))
    assert status == 200
    assert "flua" in json.loads(body)["result"]["contents"][0]["text"]
    status, body = _post(server, _rpc("prompts/get", {"name": "qa_skeleton"}))
    assert status == 200
    assert json.loads(body)["result"]["messages"]


def test_http_notification_answers_202_with_empty_body(http_server) -> None:
    status, body = _post(
        http_server(), {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert status == 202
    assert body == ""


def test_http_unsupported_protocol_version(http_server) -> None:
    status, body = _post(
        http_server(),
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "ping",
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2099-01-01"}},
        },
    )
    assert status == 200
    error = json.loads(body)["error"]
    assert error["code"] == -32022
    assert error["data"]["supported"] == ["2026-07-28", "2025-06-18"]


def test_http_invalid_json_body_answers_parse_error(http_server) -> None:
    status, body = _post(http_server(), b"{not json")
    assert status == 200
    assert json.loads(body)["error"]["code"] == -32700


# -- transport rules from the spec -------------------------------------------------


def test_http_rejects_transport_session_ids(http_server) -> None:
    # stateless mode: sessions are explicit sessionId tool arguments, never
    # an Mcp-Session-Id header — the spec says 404 for those
    status, body = _post(
        http_server(),
        _rpc("ping"),
        headers={"Mcp-Session-Id": "abc123"},
    )
    assert status == 404
    assert "stateless" in json.loads(body)["error"]["message"]


def test_http_get_and_delete_are_405(http_server) -> None:
    server = http_server()
    for method in ("GET", "DELETE"):
        status, _ = _post(server, b"", method=method)
        assert status == 405


def test_http_unknown_path_is_404(http_server) -> None:
    status, _ = _post(http_server(), _rpc("ping"), path="/nope")
    assert status == 404


def test_http_cors_preflight(http_server) -> None:
    status, _ = _post(http_server(), b"", method="OPTIONS")
    assert status == 204


def test_http_rejects_oversized_bodies(http_server) -> None:
    server = http_server()
    # the server answers 413 and drops the connection without reading the
    # body — a client mid-upload may see the 413 or a broken connection;
    # both mean the oversize body was rejected, never processed
    body = b"x" * (MAX_BODY_BYTES + 1)
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/mcp",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 413
    except (urllib.error.HTTPError, BrokenPipeError, ConnectionResetError, OSError) as exc:
        status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
        assert status in (None, 413), exc


# -- auth ---------------------------------------------------------------------------


def test_http_token_auth(http_server) -> None:
    server = http_server(token="s3cret")
    # no header → 401; wrong token → 401; right token → 200
    status, _ = _post(server, _rpc("ping"))
    assert status == 401
    status, _ = _post(server, _rpc("ping"), token="wrong")
    assert status == 401
    status, body = _post(server, _rpc("ping"), token="s3cret")
    assert status == 200
    assert json.loads(body)["result"] == {}


def test_http_nonloopback_without_token_refuses_to_start() -> None:
    with pytest.raises(ValueError, match="FLUA_MCP_TOKEN"):
        StreamableHttpServer("0.0.0.0", 0, METHODS, _check_protocol_version, token=None)


def test_http_nonloopback_with_token_starts(http_server) -> None:
    # the guard only trips without a token
    server = StreamableHttpServer(
        "127.0.0.1", 0, METHODS, _check_protocol_version, token="t"
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, _ = _post(server, _rpc("ping"), token="t")
        assert status == 200
    finally:
        server.shutdown()
        server.server_close()


# -- the real CLI -------------------------------------------------------------------


def test_cli_http_flag_serves_requests() -> None:
    # spawn `flua-mcp --http 127.0.0.1:0`, read the bound port from stderr,
    # POST a ping, and tear the process down
    process = subprocess.Popen(
        [sys.executable, "-m", "flua.mcp.server", "--http", "127.0.0.1:0"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = process.stderr.readline().strip()
        assert "listening on http://127.0.0.1:" in line, line
        port = int(line.rsplit(":", 1)[1].split("/", 1)[0])
        deadline = time.monotonic() + 10
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://127.0.0.1:{port}/mcp",
                        data=json.dumps(_rpc("ping")).encode("utf-8"),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    ),
                    timeout=2,
                ) as response:
                    assert response.status == 200
                    assert json.loads(response.read())["result"] == {}
                    break
            except (urllib.error.URLError, OSError) as exc:
                last_error = exc
                time.sleep(0.1)
        else:
            pytest.fail(f"server never answered: {last_error}")
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_cli_http_ctrl_c_exits_cleanly() -> None:
    # Ctrl-C on the HTTP transport: one stderr line, exit 130, no traceback
    import signal as _signal

    process = subprocess.Popen(
        [sys.executable, "-m", "flua.mcp.server", "--http", "127.0.0.1:0"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = process.stderr.readline().strip()
        assert "listening on http://127.0.0.1:" in line, line
        process.send_signal(_signal.SIGINT)
        # Poll instead of a hard communicate() timeout: the exit itself is
        # instant, but under heavy CI load (xdist workers on a busy runner)
        # the signal delivery and the child's KeyboardInterrupt can take a
        # while to be scheduled — the 0.1.61 release run flaked exactly this
        # way (TimeoutExpired after 15 s on an idle server). Slowness must
        # not fail the test; a wedged child still does (terminate -> the
        # 130/line/no-traceback contract below fails loudly).
        deadline = time.monotonic() + 30.0
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if process.poll() is None:
            process.terminate()
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 130
        assert "flua-mcp: interrupted" in stderr
        assert "Traceback" not in stderr
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
