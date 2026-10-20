"""net.HTTPClient: the blocking urllib glue and the engine's async wiring."""

import asyncio
import json
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine
from flua.http import http_call

pytestmark = pytest.mark.slow  # real wall-clock waits (sleeps, settles, timeouts)


async def _wait_for_output(capsys, needle: str, timeout: float = 5.0) -> str:
    """Poll capsys until needle appears; returns the accumulated output."""
    return await _wait_for_all(capsys, [needle], timeout)


async def _wait_for_all(capsys, needles: list[str], timeout: float = 5.0) -> str:
    """Poll capsys until every needle has appeared (order-independent —
    HTTP callbacks may fire in any order). Returns the accumulated output."""
    seen = ""
    deadline = time.monotonic() + timeout
    missing = set(needles)
    while missing:
        if time.monotonic() > deadline:
            raise AssertionError(f"not seen: {sorted(missing)!r}; output so far:\n{seen}")
        await asyncio.sleep(0.01)
        seen += capsys.readouterr().out
        missing = {n for n in missing if n not in seen}
    return seen


class _Handler(BaseHTTPRequestHandler):
    def _respond(self):
        if self.path.startswith("/hold-sse"):
            # one event, then HOLD: the QA's exit() must not wait for the
            # open stream's read timeout
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: one\n\n")
            self.wfile.flush()
            time.sleep(120)
            return
        if self.path.startswith("/sse"):
            # text/event-stream: a few events, then close — the HC3's success
            # fires per event and the stream end is silent
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i in range(1, 4):
                self.wfile.write(f"data: hello {i}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.05)
            return
        if self.path.startswith("/slow"):
            time.sleep(1.0)  # slow enough that the 0.2s timeout test times out
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
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
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
    status, body, _ = http_call("POST", http_server + "/post", {"X-Custom": "v"}, "hello body")
    assert status == 200
    data = json.loads(body)
    assert data["method"] == "POST"
    assert data["body"] == "hello body"


def test_http_call_timeout_raises(http_server: str) -> None:
    with pytest.raises(TimeoutError):
        http_call("GET", http_server + "/slow", timeout=0.2)


def test_http_call_refused_raises() -> None:
    with pytest.raises(urllib.error.URLError):
        http_call("GET", "http://127.0.0.1:1/x", timeout=1.0)


def _https_server(cert_dir: str):
    """A local HTTPS server with a self-signed certificate (tests/certs)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(Path(cert_dir) / "cert.pem", Path(cert_dir) / "key.pem")
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    return httpd, f"https://127.0.0.1:{httpd.server_port}/"


@pytest.mark.asyncio
async def test_http_check_certificate_option(tmp_path, capsys) -> None:
    # the HC3's checkCertificate option: false skips HTTPS verification
    # (self-signed certs — very common in QA code); true (the default) fails
    httpd, url = _https_server(str(Path(__file__).parent / "certs"))
    try:
        script = tmp_path / "tls.lua"
        script.write_text(
            "function QuickApp:onInit()\n"
            "  local client = net.HTTPClient()\n"
            f"  client:request('{url}', {{\n"
            "    options = { checkCertificate = false },\n"
            "    success = function(resp) print('OK', resp.status, resp.data) end,\n"
            "    error = function(e) print('ERR1', tostring(e)) end,\n"
            "  })\n"
            f"  client:request('{url}', {{\n"
            "    options = {},\n"
            "    success = function(resp) print('SHOULD_NOT_SUCCEED', resp.status) end,\n"
            "    error = function(e) print('ERR2', tostring(e)) end,\n"
            "  })\n"
            "end\n"
        )
        engine = LuaEngine()
        await engine.start()
        try:
            engine.start_qa(str(script), None, {}, str(script))
            out = await _wait_for_all(capsys, ["OK 200", "ERR2"])
        finally:
            await engine.stop()
        assert "OK 200" in out  # verification skipped
        assert "SHOULD_NOT_SUCCEED" not in out
        assert "ERR2" in out  # the default verifies, the self-signed cert fails
    finally:
        httpd.shutdown()


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
        out = await _wait_for_all(capsys, ["OK 200 true yes", "NOTFOUND 404", "TRANSPORT true"])
    finally:
        await engine.stop()
    assert "OK 200 true yes" in out
    assert "NOTFOUND 404" in out
    assert "TRANSPORT true" in out
    assert "SHOULD_NOT_FIRE" not in out  # transport failures must not reach success


@pytest.mark.asyncio
async def test_http_client_constructor_timeout(tmp_path, capsys, http_server: str) -> None:
    # net.HTTPClient({timeout}) sets the per-request default;
    # params.options.timeout overrides it per request
    script = tmp_path / "httptimeout.lua"
    script.write_text(
        "local client = net.HTTPClient({timeout = 200})\n"
        "setTimeout(function()\n"
        "  client:request('" + http_server + "/slow', {\n"
        "    error = function(err) print('CTIMEOUT', err ~= nil) end,\n"
        "  })\n"
        "  client:request('" + http_server + "/slow', {\n"
        "    options = { timeout = 5000 },\n"
        "    success = function(resp) print('COVERRIDE', resp.status) end,\n"
        "    error = function(err) print('COVERRIDE_ERR', err) end,\n"
        "  })\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        out = await _wait_for_all(capsys, ["CTIMEOUT true", "COVERRIDE 200"])
    finally:
        await engine.stop()
    assert "CTIMEOUT true" in out  # the constructor timeout timed the request out
    assert "COVERRIDE 200" in out  # the per-request option overrode it
    assert "COVERRIDE_ERR" not in out


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
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALIVE 200" in result.stdout


def test_http_debug_flag_logs_client_requests(tmp_path, http_server: str) -> None:
    # --%%debug:http=true logs user net.HTTPClient traffic — and only that,
    # never the api.* calls (which have their own --%%debug:api flag)
    script = tmp_path / "dbg.lua"
    script.write_text(
        "--%%debug:http=true\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function()\n"
        "  net.HTTPClient():request('" + http_server + "/get', {\n"
        "    success = function(resp) print('OK', resp.status) end,\n"
        "    error = function(err) print('ERR', err) end,\n"
        "  })\n"
        "end, 20)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "http GET " + http_server + "/get" in result.stdout
    assert "api GET" not in result.stdout  # http does not cover api calls
    assert "OK 200" in result.stdout


def test_example_http_runs_cleanly() -> None:
    # examples/http.lua hits httpbin.org, so the suite must not depend on the
    # network: assert the deterministic parts — clean exit, the refused
    # connection reported through the error callback, no traceback.
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/http.lua"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "refused:" in result.stdout
    assert "SHOULD NOT HAPPEN" not in result.stdout
    assert "stack traceback" not in result.stdout


@pytest.mark.asyncio
async def test_http_sse_streams_events(tmp_path, capsys, http_server: str) -> None:
    # a text/event-stream response delivers each RAW event block to success
    # (more=True keeps the entry alive); the stream end is silent — the HC3
    # quirk: no extra callback, no error
    script = tmp_path / "sse.lua"
    script.write_text(
        "local n = 0\n"
        "net.HTTPClient():request('" + http_server + "/sse', {\n"
        "  success = function(resp)\n"
        "    n = n + 1\n"
        "    print('EVENT', n, resp.status, resp.data)\n"
        "  end,\n"
        "  error = function(e) print('ERR', e) end,\n"
        "})\n"
        "setTimeout(function() print('COUNT', n); exit(n == 3 and 0 or 1) end, 500)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        out = await _wait_for_all(capsys, ["EVENT 3", "COUNT 3"])
    finally:
        await engine.stop()
    assert "EVENT 1 200 data: hello 1" in out
    assert "EVENT 2 200 data: hello 2" in out
    assert "EVENT 3 200 data: hello 3" in out
    assert "COUNT 3" in out  # exactly three: the close delivered nothing
    assert "ERR" not in out


@pytest.mark.asyncio
async def test_qa_exit_cancels_open_sse_stream(tmp_path, capsys, http_server: str) -> None:
    # exit() in a QA cancels its in-flight requests: an open SSE stream must
    # not keep the run alive until its (very long) read timeout
    script = tmp_path / "exit.lua"
    script.write_text(
        "net.HTTPClient({timeout = 300000}):request('" + http_server + "/hold-sse', {\n"
        "  success = function(resp) print('EVENT', resp.data) end,\n"
        "  error = function(e) print('ERR', e) end,\n"
        "})\n"
        "setTimeout(function() print('EXITING'); exit(0) end, 100)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await _wait_for_all(capsys, ["EXITING"])
        deadline = time.monotonic() + 2.0
        while engine.has_pending_work() and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert not engine.has_pending_work()  # the stream died with the QA
    finally:
        await engine.stop()
