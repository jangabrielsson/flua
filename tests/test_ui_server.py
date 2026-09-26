"""ApiServer tests — the UI viewer's channel: the sim API over HTTP.

These pin the contract the viewer (viewer/index.html) relies on: device/UI
state over ``GET /devices``, interactions over ``GET /plugins/callUIEvent``,
runtime UI state over ``/plugins/updateView`` + ``device.view``, CORS, and
the rule that the listener is never pending work.

House rule for this file: every HTTP call must go through
``asyncio.to_thread`` (the ``_http``/``_http_raw`` helpers). The ApiServer
runs on the same event loop these tests await on, so a blocking
``urllib.request.urlopen`` deadlocks the loop and the whole pytest run
hangs with no output. This actually happened — ``test_options_preflight``
used to call urlopen directly and hung the suite.
"""

import asyncio
import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402
from flua.http_server import ApiServer  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _http(url: str, method: str = "GET", body: object = None) -> tuple[int, dict, object]:
    req = urllib.request.Request(url, method=method)
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as res:
        payload = res.read()
        return res.status, dict(res.headers), json.loads(payload) if payload else None


def _http_raw(url: str, method: str, raw_body: bytes) -> None:
    req = urllib.request.Request(url, data=raw_body, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req):
        pass


@pytest.fixture
async def server(tmp_path):
    engine = LuaEngine()
    await engine.start()
    api_server = ApiServer(engine.api, port=0)
    await api_server.start()
    base = f"http://127.0.0.1:{api_server.port}"
    yield engine, api_server, base
    await api_server.stop()
    await engine.stop()


@pytest.mark.asyncio
async def test_devices_over_http(server, tmp_path) -> None:
    engine, _, base = server
    script = tmp_path / "ui.lua"
    script.write_text('--%%u:{button="B1",text="Press me",onReleased="fopp"}\n')
    engine.load_qa_file(str(script))
    await asyncio.sleep(0.3)
    status, headers, data = await asyncio.to_thread(_http, f"{base}/devices")
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == "*"
    qa = next(d for d in data if d["id"] == 5000)
    assert qa["properties"]["uiView"][0]["components"][0]["name"] == "B1"


@pytest.mark.asyncio
async def test_call_ui_event_over_http(server, tmp_path, capsys) -> None:
    engine, _, base = server
    script = tmp_path / "ui.lua"
    script.write_text(
        '--%%u:{button="B1",text="Press me",onReleased="fopp"}\n'
        "function QuickApp:fopp() print('PRESSED') end\n"
    )
    engine.load_qa_file(str(script))
    await asyncio.sleep(0.3)
    url = f"{base}/plugins/callUIEvent?deviceID=5000&elementName=B1&eventType=onReleased"
    status, _, data = await asyncio.to_thread(_http, url)
    assert status == 200
    await asyncio.sleep(0.3)
    assert "PRESSED" in capsys.readouterr().out
    # the same validation as in-process applies over HTTP
    with pytest.raises(urllib.error.HTTPError) as exc:
        await asyncio.to_thread(_http, f"{base}/plugins/callUIEvent?deviceID=5000")
    assert exc.value.code == 400


@pytest.mark.asyncio
async def test_update_view_visible_over_http(server, tmp_path) -> None:
    # QuickApp:updateView lands in device.view — what the viewer merges over
    # the component definitions when it renders
    engine, _, base = server
    script = tmp_path / "ui.lua"
    script.write_text(
        '--%%u:{label="l1",text="Old text"}\n'
        "function QuickApp:onInit()\n"
        "  self:updateView('l1','text','new label text')\n"
        "end\n"
    )
    engine.load_qa_file(str(script))
    await asyncio.sleep(0.4)
    status, _, device = await asyncio.to_thread(_http, f"{base}/devices/5000")
    assert status == 200
    assert device["view"]["l1"]["text"] == "new label text"


@pytest.mark.asyncio
async def test_update_view_post_over_http(server, tmp_path) -> None:
    engine, _, base = server
    script = tmp_path / "ui.lua"
    script.write_text('--%%u:{label="l1",text="Old text"}\n')
    engine.load_qa_file(str(script))
    await asyncio.sleep(0.3)
    status, _, data = await asyncio.to_thread(
        _http,
        f"{base}/plugins/updateView",
        method="POST",
        body={"deviceId": 5000, "componentName": "l1", "propertyName": "text", "newValue": "hello"},
    )
    assert status == 204
    _, _, device = await asyncio.to_thread(_http, f"{base}/devices/5000")
    assert device["view"]["l1"]["text"] == "hello"


@pytest.mark.asyncio
async def test_options_preflight(server) -> None:
    _, _, base = server
    # urlopen is blocking — offload it, or it deadlocks the loop the server
    # runs on (the other tests do the same via asyncio.to_thread)
    status, headers, _ = await asyncio.to_thread(_http, f"{base}/devices", method="OPTIONS")
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "Authorization" in headers["Access-Control-Allow-Headers"]


@pytest.mark.asyncio
async def test_bad_json_body_is_400(server) -> None:
    _, _, base = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        await asyncio.to_thread(_http_raw, f"{base}/plugins/updateView", "POST", b"{not json")
    assert exc.value.code == 400


@pytest.mark.asyncio
async def test_server_does_not_keep_engine_alive(server, tmp_path) -> None:
    # the listener is a viewer channel, not engine work: a drained run still
    # reports nothing pending while the server stays up
    engine, _, _ = server
    script = tmp_path / "idle.lua"
    script.write_text("setTimeout(function() end, 20)\n")
    engine.load_qa_file(str(script))
    await asyncio.sleep(0.4)
    assert not engine.has_pending_work()


def test_ui_flag_keeps_api_alive_after_qa_drains(tmp_path) -> None:
    # The viewer's channel must outlive the QA's timers: `flua --ui` with no
    # --run-for serves the sim API until interrupted. A QA with no timers
    # would drain immediately and (before the ui_keepalive fix) take the
    # server down with it — the viewer would lose its API seconds after
    # launch. Pin the behavior end to end through the real CLI.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    script = tmp_path / "ui.lua"
    script.write_text(
        '--%%u:{button="B1",text="Press me",onReleased="go"}\n'
        "function QuickApp:go() end\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "flua", "--api", "local", "--ui", str(port), str(script)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15.0
        saw_button = False
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/devices", timeout=0.5
                ) as res:
                    devices = json.loads(res.read())
                saw_button = any(
                    component.get("name") == "B1"
                    for device in devices
                    for row in (device.get("properties") or {}).get("uiView") or []
                    for component in row.get("components") or []
                )
                if saw_button:
                    break
            except (OSError, ValueError):
                time.sleep(0.1)
        assert proc.poll() is None, (
            "flua --ui exited before serving the API: " + proc.stdout.read()
        )
        assert saw_button, "UI API never served the QA device"
        # the QA has no timers — a plain run would have drained and exited by
        # now; the UI session must still be alive and answering
        time.sleep(1.0)
        assert proc.poll() is None, "flua --ui exited after the QA drained"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/devices", timeout=2) as res:
            assert json.loads(res.read())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def test_ui_port_busy_falls_back_to_next_free_port(tmp_path) -> None:
    # parallel runs and quick restarts must not collide: when the requested
    # port is busy, flua serves on the next free port and announces the
    # effective URL (a second `flua --ui 8090` while the first runs used to
    # die with an OSError traceback)
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)  # keep the port occupied for the whole test
    port = busy.getsockname()[1]

    script = tmp_path / "ui.lua"
    script.write_text(
        '--%%u:{button="B1",text="Press me",onReleased="go"}\n'
        "function QuickApp:go() end\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "flua", "--api", "local", "--ui", str(port), str(script)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        announce_re = re.compile(r"UI API on http://127\.0\.0\.1:(\d+)")
        served_port = None
        output = ""
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and proc.poll() is None:
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            output += line
            match = announce_re.search(line)
            if match:
                served_port = int(match.group(1))
                break
        assert proc.poll() is None, "flua --ui exited early: " + output
        assert served_port is not None, "flua --ui never announced its port: " + output
        assert served_port != port, "flua served on the busy port"
        assert served_port > port, "fallback moved backwards: " + output
        assert f"port {port} busy" in output, "no busy-port notice: " + output
        # the fallback listener actually serves the sim API
        with urllib.request.urlopen(
            f"http://127.0.0.1:{served_port}/devices", timeout=2
        ) as res:
            assert json.loads(res.read())
    finally:
        busy.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)