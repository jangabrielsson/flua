"""net.HTTPClient: the blocking urllib glue and the engine's async wiring."""

import asyncio
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine
from flua.http import http_call


class _Handler(BaseHTTPRequestHandler):
    def _respond(self):
        if self.path.startswith("/slow"):
            time.sleep(2.0)
        payload = json.dumps(
            {"method": self.command, "path": self.path, "body": self._body or None}
        ).encode()
        status = 404 if self.path.startswith("/status/404") else 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Test", "yes")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._body = None
        self._respond()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self._body = self.rfile.read(length).decode("utf-8")
        self._respond()

    def log_message(self, *args):  # silence
        pass


@pytest.fixture(scope="module")
def http_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


# -- the blocking urllib glue ---------------------------------------------------


def test_http_call_get(http_server: str) -> None:
    status, body, headers = http_call("GET", http_server + "/get")
    assert status == 200
    data = json.loads(body)
    assert data["path"] == "/get"
    assert headers["X-Test"] == "yes"


def test_http_call_404_reaches_success(http_server: str) -> None:
    # completed exchanges (even 4xx) return a status, they don't raise
    status, _, _ = http_call("GET", http_server + "/status/404")
    assert status == 404


def test_http_call_post_body_and_headers(http_server: str) -> None:
    status, body, _ = http_call(
        "POST", http_server + "/post", {"X-Custom": "v"}, "hello body"
    )
    assert status == 200
    data = json.loads(body)
    assert data["method"] == "POST"
    assert data["body"] == "hello body"


def test_http_call_timeout_raises(http_server: str) -> None:
    with pytest.raises(Exception):
        http_call("GET", http_server + "/slow", timeout=0.2)


def test_http_call_refused_raises() -> None:
    with pytest.raises(Exception):
        http_call("GET", "http://127.0.0.1:1/x", timeout=1.0)


# -- engine wiring: Lua request -> pump -> callback ------------------------------


@pytest.mark.asyncio
async def test_http_client_lua_roundtrip(tmp_path, capsys, http_server: str) -> None:
    script = tmp_path / "netuser.lua"
    script.write_text(
        "local client = net.HTTPClient()\n"
        "setTimeout(function()\n"
        "  client:request('" + http_server + "/get', {\n"
        "    success = function(resp)\n"
        "      print('OK', resp.status, resp.data ~= nil, resp.headers['X-Test'])\n"
        "    end,\n"
        "    error = function(err) print('ERR', err) end,\n"
        "  })\n"
        "  client:request('" + http_server + "/status/404', {\n"
        "    success = function(resp) print('NOTFOUND', resp.status) end,\n"
        "  })\n"
        "  client:request('http://127.0.0.1:1/x', {\n"
        "    success = function(resp) print('SHOULD_NOT_FIRE') end,\n"
        "    error = function(err) print('TRANSPORT', err ~= nil) end,\n"
        "  })\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(1.0)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "OK 200 true yes" in out
    assert "NOTFOUND 404" in out
    assert "TRANSPORT true" in out
    assert "SHOULD_NOT_FIRE" not in out  # transport failures must not reach success


def test_http_keeps_process_alive_until_response(tmp_path, http_server: str) -> None:
    # the CLI's graceful exit must wait for in-flight HTTP requests: no
    # --run-for, no other pending work — the response callback still runs
    script = tmp_path / "alive.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  net.HTTPClient():request('" + http_server + "/get', {\n"
        "    success = function(resp) print('ALIVE', resp.status) end,\n"
        "    error = function(err) print('ERR', err) end,\n"
        "  })\n"
        "end, 20)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALIVE 200" in result.stdout


def test_example_http_runs_cleanly() -> None:
    # examples/http.lua hits httpbin.org, so the suite must not depend on the
    # network: assert the deterministic parts — clean exit, the refused
    # connection reported through the error callback, no traceback.
    result = subprocess.run(
        [sys.executable, "-m", "flua", "examples/http.lua"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "refused:" in result.stdout
    assert "SHOULD NOT HAPPEN" not in result.stdout
    assert "stack traceback" not in result.stdout