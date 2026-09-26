"""M3: the remote HC3 backend — hybrid routing and the auth-lockout guard.

Tests run against a local mock HC3 (a threaded HTTP server), never a real
controller.
"""

import asyncio
import base64
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine

REPO_ROOT = Path(__file__).resolve().parent.parent

GOOD_CREDS = "Basic " + base64.b64encode(b"admin:secret").decode()


class _MockHc3(BaseHTTPRequestHandler):
    """A tiny HC3: settings info, one device (id 45), basic-auth enforced."""

    requests_seen: list[str] = []
    refresh_events_sent = False  # serve the event feed exactly once per run
    refresh_polls = 0
    auth_all = False  # when set, every endpoint requires valid basic auth
    hold_refresh = 0.0  # hold the refreshStates response this many seconds (SIGINT tests)

    def _send_json(self, data, status: int = 200) -> None:
        payload = json.dumps(data).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            pass  # the client gave up (e.g. killed by SIGINT mid-poll)

    def _authed(self) -> bool:
        return self.headers.get("Authorization") == GOOD_CREDS

    def do_GET(self):
        type(self).requests_seen.append(self.path)
        if self.path.startswith("/api/devices/45"):
            if not self._authed():
                self._send_json({"error": "unauthorized"}, 401)
                return
            self._send_json({"id": 45, "name": "hc3-device", "type": "com.fibaro.binarySwitch"})
            return
        if self.path.startswith("/api/settings/info"):
            self._send_json({"serialNumber": "HC3-00000422", "softVersion": "5.210.12"})
            return
        if self.path.startswith("/api/refreshStates"):
            if type(self).auth_all and not self._authed():
                self._send_json({"error": "unauthorized"}, 401)
                return
            if type(self).hold_refresh:
                time.sleep(type(self).hold_refresh)
            type(self).refresh_polls += 1
            now = int(time.time())
            # the event arrives on the SECOND poll — after QAs have had time
            # to register their subscribers (a first-poll event would race)
            if type(self).refresh_polls == 2 and not type(self).refresh_events_sent:
                type(self).refresh_events_sent = True
                self._send_json(
                    {
                        "status": "IDLE",
                        "last": 5,
                        "date": "x",
                        "timestamp": 1,
                        "timestampMillis": now * 1000,
                        "events": [
                            {
                                "type": "DevicePropertyUpdatedEvent",
                                "created": now,
                                "createdMillis": now * 1000,
                                "sourceType": "system",
                                "sourceId": 0,
                                "objects": [{"objectType": "device", "objectId": 45}],
                                "data": {"id": 45, "property": "value", "newValue": True},
                            }
                        ],
                    }
                )
                return
            self._send_json(
                {
                    "status": "IDLE",
                    "last": 5,
                    "date": "x",
                    "timestamp": now,
                    "timestampMillis": now * 1000,
                }
            )
            return
        self._send_json({"error": "not found"}, 404)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def mock_hc3() -> str:
    _MockHc3.requests_seen = []
    _MockHc3.refresh_events_sent = False
    _MockHc3.refresh_polls = 0
    _MockHc3.auth_all = False
    _MockHc3.hold_refresh = 0.0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


async def _run_qa(script: str, sleep: float = 0.6, capsys=None) -> str:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/qa.lua"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        engine = LuaEngine(api_mode="remote")
        await engine.start()
        try:
            engine.start_qa(path, None, {}, path)
            await asyncio.sleep(sleep)
        finally:
            await engine.stop()
    return capsys.readouterr().out


@pytest.mark.asyncio
async def test_hybrid_routing_local_sim_and_remote_hc3(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # the QA itself (id 5000) comes from the sim; device 45 comes from the
    # mock HC3 — one api.get call each, same Lua surface
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # isolate from the user's ~/.env
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    script = tmp_path / "hybrid.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  local localDev = api.get('/devices/'.._FLUA.qaId)\n"
        "  local remoteDev, status = api.get('/devices/45')\n"
        "  print('LOCAL', localDev.id)\n"
        "  print('REMOTE', status, remoteDev.name)\n"
        "end, 20)\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.5)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "LOCAL 5000" in out  # served by the offline sim
    assert "REMOTE 200 hc3-device" in out  # served by the mock HC3


@pytest.mark.asyncio
async def test_auth_failure_aborts_immediately(
    tmp_path, capsys, caplog, mock_hc3, monkeypatch
) -> None:
    # wrong password -> 401 -> loud warning + exit(1), exactly ONE attempt
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # isolate from the user's ~/.env
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "WRONG")
    script = tmp_path / "auth.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  local d, status = api.get('/devices/45')\n"
        "  print('GOT', status)\n"
        "end, 20)\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.5)
    finally:
        await engine.stop()
    captured = capsys.readouterr()
    assert "HC3 authentication failed" not in captured.out  # one channel only
    records = [r for r in caplog.records if "HC3 authentication failed" in r.getMessage()]
    assert len(records) == 1  # logged once (stderr in a real CLI run)
    assert "locks itself after 4 wrong attempts" in records[0].getMessage()
    assert engine.exit_code == 1
    device_requests = [r for r in _MockHc3.requests_seen if r.startswith("/api/devices/45")]
    assert len(device_requests) == 1  # never retried


@pytest.mark.asyncio
async def test_api_hc3_bypasses_the_hybrid_dispatch(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # api.get serves the local QA (id 5000) from the sim; api.hc3.get must
    # bypass the sim and ask the mock HC3 — which doesn't know device 5000.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    script = tmp_path / "bypass.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  local simDev = api.get('/devices/'.._FLUA.qaId)\n"
        "  local hc3Dev, hc3Status = api.hc3.get('/devices/'.._FLUA.qaId)\n"
        "  print('SIM', simDev.name)\n"
        "  print('HC3', hc3Status, hc3Dev)\n"
        "  local remoteDev, status = api.hc3.get('/devices/45')\n"
        "  print('REMOTE', status, remoteDev.name)\n"
        "end, 20)\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.5)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "SIM bypass" in out  # the hybrid dispatch: local sim first
    assert "HC3 404" in out  # api.hc3 skipped the sim; the mock 404s on 5000
    assert "REMOTE 200 hc3-device" in out  # and reaches the mock's device 45


@pytest.mark.asyncio
async def test_flua_namespace_ids_never_forward(tmp_path, capsys, mock_hc3, monkeypatch) -> None:
    # ids >= 5000 belong to flua even if the device is not loaded yet: their
    # 404s are local answers, never forwarded to the real HC3
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    script = tmp_path / "ns.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  local d, s = api.get('/devices/5001/properties/value')\n"
        "  print('FLOA_NS', s)\n"
        "  local e, s2 = api.get('/devices/45')\n"
        "  print('HC3_NS', s2, e and e.name)\n"
        "end, 20)\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.5)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "FLOA_NS 404" in out  # answered locally, no forwarding
    assert "HC3_NS 200 hc3-device" in out  # lower ids still reach the HC3
    forwarded = [r for r in _MockHc3.requests_seen if r.startswith("/api/devices/5001")]
    assert forwarded == []


@pytest.mark.asyncio
async def test_api_hc3_falls_back_to_sim_offline(tmp_path, capsys, monkeypatch) -> None:
    # local mode: no remote backend, so api.hc3 stands in for the sim
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    script = tmp_path / "fallback.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  local dev = api.hc3.get('/devices/'.._FLUA.qaId)\n"
        "  print('FALLBACK', dev.id)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()
    assert "FALLBACK 5000" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_refresh_state_subscriber_receives_sim_events(tmp_path, capsys, monkeypatch) -> None:
    # a QA's RefreshStateSubscriber gets pump-delivered events for sim state
    # changes (the plua bridge hack replaced by a message)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    script = tmp_path / "sub.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  local sub = RefreshStateSubscriber()\n"
        "  sub:subscribe(function(e) return e.type == 'DeviceActionRanEvent' end, function(e)\n"
        "    print('SUB', e.type, e.data.actionName)\n"
        "  end)\n"
        "  sub:run()\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.2)
        engine.api.dispatch("POST", "/devices/5000/action/toggle", {"args": []})
        await asyncio.sleep(0.3)
        assert "SUB DeviceActionRanEvent toggle" in capsys.readouterr().out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_online_poller_mirrors_events_into_buffer(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # online mode: the poller long-polls the (mock) HC3's refreshStates and
    # mirrors events into the local buffer + the Lua subscribers
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    script = tmp_path / "sub.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  local sub = RefreshStateSubscriber()\n"
        "  sub:subscribe(function(e) return true end, function(e)\n"
        "    print('MIRROR', e.type, e.data.id)\n"
        "  end)\n"
        "  sub:run()\n"
        "end, 20)\n"
        "setTimeout(function()\n"
        "  local data = api.get('/refreshStates?last=0')\n"
        "  for _, e in ipairs(data.events or {}) do print('BUFFER', e.type) end\n"
        "end, 4000)\n"  # after the second poll mirrors the event
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(4.5)  # past the 4000 ms BUFFER timer
        out = capsys.readouterr().out
        assert "MIRROR DevicePropertyUpdatedEvent 45" in out
        assert "BUFFER DevicePropertyUpdatedEvent" in out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_keep_alive_directive_keeps_engine_pending(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # --%%keep-alive:true keeps the online engine pending past idle (like a QA
    # on the real HC3, which runs forever); without it the run drains and the
    # engine is done — the poller alone must never hold the process open.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    script = tmp_path / "idle.lua"

    script.write_text("setTimeout(function() print('DONE') end, 50)\n")
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.6)
        out = capsys.readouterr().out
        assert "DONE" in out
        assert not engine.has_pending_work()  # idle run drains despite the poller
    finally:
        await engine.stop()

    script.write_text("--%%keep-alive:true\nsetTimeout(function() print('KEEP') end, 50)\n")
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.load_qa_file(str(script))  # parses the --%% header like the CLI
        await asyncio.sleep(0.6)
        out = capsys.readouterr().out
        assert "KEEP" in out
        assert engine.has_pending_work()  # the keep-alive QA holds the engine open
    finally:
        await engine.stop()

    # a keep-alive QA that exits releases the hold (exit() records a falsy 0)
    script.write_text("--%%keep-alive:true\nsetTimeout(function() exit() end, 50)\n")
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.load_qa_file(str(script))
        await asyncio.sleep(0.6)
        assert not engine.has_pending_work()  # the exited QA no longer holds it
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_poller_auth_failure_stops_after_one_attempt(
    tmp_path, capsys, caplog, mock_hc3, monkeypatch
) -> None:
    # the poller is usually the FIRST thing to hit the HC3 — wrong credentials
    # must cost exactly ONE attempt against the 4-attempt lockout budget
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "WRONG")
    _MockHc3.auth_all = True  # every endpoint (incl. refreshStates) now 401s
    engine = LuaEngine(api_mode="remote")
    try:
        await engine.start()
        try:
            await asyncio.sleep(1.5)  # several poll cycles would fit here
        finally:
            await engine.stop()
    finally:
        _MockHc3.auth_all = False
    polls = [r for r in _MockHc3.requests_seen if r.startswith("/api/refreshStates")]
    assert len(polls) == 1  # the poller never retries an auth failure
    assert engine.exit_code == 1
    captured = capsys.readouterr()
    assert "HC3 authentication failed" not in captured.out  # one channel only
    records = [r for r in caplog.records if "HC3 authentication failed" in r.getMessage()]
    assert len(records) == 1  # logged once (stderr in a real CLI run)
    assert "locks itself after 4 wrong attempts" in records[0].getMessage()


def _hc3_env(mock_url: str, home: str) -> dict[str, str]:
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith("HC3_")},
        "HC3_URL": mock_url,
        "HC3_USER": "admin",
        "HC3_PASSWORD": "secret",
        "HOME": home,
    }


def test_cli_defaults_to_online_with_hc3_env(tmp_path, mock_hc3) -> None:
    # no --api flag, no --%%offline: the engine picks online because the
    # environment carries HC3 credentials (plua behavior)
    script = tmp_path / "main.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  local d, s = api.get('/devices/45')\n"
        "  print('MODE', s, d and d.name)\n"
        "end, 20)\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=tmp_path,  # isolated from the developer's .directives
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MODE 200 hc3-device" in result.stdout


def test_ctrl_c_terminates_promptly_mid_long_poll(tmp_path, mock_hc3) -> None:
    # Ctrl-C must not wait out a held refreshStates long poll: the request
    # runs on a daemon thread, so the process exits right away (code 130).
    # (Before the daemon thread, asyncio.run joined the abandoned executor
    # worker — exit waited out the mock's full 20s hold.)
    script = tmp_path / "keep.lua"
    script.write_text("--%%keep-alive:true\nprint('KA')\n")
    home = tmp_path / "home"
    home.mkdir()
    _MockHc3.hold_refresh = 20.0
    proc = subprocess.Popen(
        [sys.executable, "-m", "flua", str(script)],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=tmp_path,  # isolated from the developer's .directives
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(1.0)  # the keep-alive long poll is in flight, held 20s
        started = time.monotonic()
        proc.send_signal(signal.SIGINT)
        _out, err = proc.communicate(timeout=10)
    finally:
        _MockHc3.hold_refresh = 0.0
        if proc.poll() is None:
            proc.kill()
    assert time.monotonic() - started < 5.0  # prompt exit, not the 20s hold
    assert proc.returncode == 130
    assert "flua: interrupted" in err.decode()


def test_cli_main_file_offline_directive_forces_sim(tmp_path, mock_hc3) -> None:
    # the MAIN QA's --%%offline:true (peeked before the engine starts)
    # selects offline mode even with HC3 credentials present
    script = tmp_path / "main.lua"
    script.write_text(
        "--%%offline:true\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function()\n"
        "  local d, s = api.get('/devices/45')\n"
        "  print('MODE', s)\n"
        "end, 20)\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MODE 404" in result.stdout  # served by the sim, never forwarded
    assert not any(r.startswith("/api/devices/45") for r in _MockHc3.requests_seen)


def test_cli_main_file_mode_offline_forces_sim(tmp_path, mock_hc3) -> None:
    # the MAIN QA's --%%mode:offline (peeked before the engine starts)
    # selects offline mode even with HC3 credentials present
    script = tmp_path / "main.lua"
    script.write_text(
        "--%%mode:offline\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function()\n"
        "  local d, s = api.get('/devices/45')\n"
        "  print('MODE', s)\n"
        "end, 20)\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MODE 404" in result.stdout  # served by the sim, never forwarded
    assert not any(r.startswith("/api/devices/45") for r in _MockHc3.requests_seen)


def test_cli_main_file_mode_online_forces_remote_without_credentials(tmp_path) -> None:
    # the MAIN QA's --%%mode:online selects the real HC3 — without HC3
    # credentials the engine refuses to start (like --api remote)
    home = tmp_path / "home"
    home.mkdir()
    script = tmp_path / "main.lua"
    script.write_text("--%%mode:online\nprint('x')\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("HC3_")},
            "HOME": str(home),
        },
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "HC3_URL" in result.stderr


@pytest.mark.asyncio
async def test_offline_directive_pins_secondary_qa_to_sim(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # in an online run, a SECONDARY QA with --%%offline:true stays in the sim
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    a = tmp_path / "a.lua"
    a.write_text(
        "setTimeout(function() local d, s = api.get('/devices/45'); "
        "print('A', s, d and d.name) end, 20)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "--%%offline:true\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function() local d, s = api.get('/devices/45'); print('B', s) end, 30)\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.load_qa_file(str(a))
        engine.load_qa_file(str(b))
        await asyncio.sleep(0.5)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "A 200 hc3-device" in out  # the online QA reaches the mock HC3
    assert "B 404" in out  # the pinned QA stays in the sim


@pytest.mark.asyncio
async def test_mode_directive_pins_secondary_qa_to_sim(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # like test_offline_directive_pins_secondary_qa_to_sim, but with the
    # canonical --%%mode:offline
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    a = tmp_path / "a.lua"
    a.write_text(
        "setTimeout(function() local d, s = api.get('/devices/45'); "
        "print('A', s, d and d.name) end, 20)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "--%%mode:offline\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function() local d, s = api.get('/devices/45'); print('B', s) end, 30)\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.load_qa_file(str(a))
        engine.load_qa_file(str(b))
        await asyncio.sleep(0.5)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "A 200 hc3-device" in out  # the online QA reaches the mock HC3
    assert "B 404" in out  # the pinned QA stays in the sim


def test_cli_default_mode_is_online(tmp_path, monkeypatch) -> None:
    # no --api flag and no --%%mode directive: ONLINE is the default — with
    # no HC3 credentials the engine refuses to start (offline is opt-in)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("HC3_URL", raising=False)
    monkeypatch.delenv("HC3_HOST", raising=False)
    script = tmp_path / "x.lua"
    script.write_text("print('x')\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("HC3_")},
            "HOME": str(home),
        },
        cwd=tmp_path,  # isolated from the developer's .directives
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "HC3_URL" in result.stderr


def test_cli_remote_requires_hc3_url(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("HC3_URL", raising=False)
    monkeypatch.delenv("HC3_HOST", raising=False)
    script = tmp_path / "x.lua"
    script.write_text("print('x')\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "remote", str(script)],
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("HC3_")},
            "HOME": str(home),
        },
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "HC3_URL" in result.stderr
