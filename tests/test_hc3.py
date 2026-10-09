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
import urllib.parse
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
    uploaded: list[dict] = []  # decoded .fqa packages (POST /quickApp)
    file_updates: list[tuple[int, list]] = []  # (qa_id, files) for PUT /quickApp/{id}/files
    export_post_rejects = False  # bodyless export POSTs get 400 (real-HC3 behavior)
    device_delay = 0.0  # hold /api/devices/45 this many seconds (async-dispatch tests)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode()

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
            if type(self).device_delay:
                time.sleep(type(self).device_delay)
            self._send_json({"id": 45, "name": "hc3-device", "type": "com.fibaro.binarySwitch"})
            return
        if self.path == "/api/devices" or self.path.startswith("/api/devices?"):
            if not self._authed():
                self._send_json({"error": "unauthorized"}, 401)
                return
            query = urllib.parse.parse_qs(self.path.partition("?")[2])
            parent = query.get("parentId", [None])[0]
            devices = [
                {"id": 45, "name": "hc3-device", "type": "com.fibaro.binarySwitch"},
                {"id": 46, "name": "hc3-other", "type": "com.fibaro.binarySwitch"},
            ]
            if parent is not None:
                devices = [d for d in devices if str(d.get("parentId", 0)) == parent]
            self._send_json(devices)
            return
        if self.path.startswith("/api/quickApp/export/"):
            self._send_json(
                {
                    "name": "downloaded",
                    "type": "com.fibaro.binarySwitch",
                    "files": [
                        {
                            "name": "main",
                            "isMain": True,
                            "content": "--%%name:downloaded\nprint('MAIN')\n",
                        },
                        {
                            "name": "lib",
                            "isMain": False,
                            "content": "function helper() return 42 end\n",
                        },
                    ],
                }
            )
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

    def do_POST(self):
        body = self._read_body()
        path = self.path.split("?")[0]
        if path.startswith("/api/quickApp/export/"):
            # some firmware versions reject the export POST altogether (a
            # bodyless one is always a 400 on the real HC3); the deprecated
            # GET still works — the tool falls back to it
            if type(self).export_post_rejects:
                self._send_json({"error": "bad body"}, 400)
                return
            self._send_json(
                {
                    "name": "downloaded",
                    "type": "com.fibaro.binarySwitch",
                    "initialProperties": {
                        "uiView": [
                            {
                                "type": "horizontal",
                                "components": [
                                    {"type": "label", "name": "lbl", "text": "Status"},
                                    {"type": "button", "name": "goBtn", "text": "Go"},
                                ],
                            },
                            {
                                "type": "horizontal",
                                "components": [
                                    {
                                        "type": "slider",
                                        "name": "dim",
                                        "text": "Brightness",
                                        "min": "0",
                                        "max": "100",
                                        "step": "1",
                                        "value": "50",
                                    }
                                ],
                            },
                        ],
                        "uiCallbacks": [
                            {"name": "goBtn", "eventType": "onReleased", "callback": "goNow"},
                            {"name": "dim", "eventType": "onChanged", "callback": "dimChanged"},
                        ],
                        "quickAppVariables": [{"name": "speed", "value": "42"}],
                    },
                    "files": [
                        {
                            "name": "main",
                            "isMain": True,
                            "content": (
                                "--%%name:OLD\n"
                                "--%%mode:offline\n"
                                "-- --------------- EOH ---------------\n"
                                "print('MAIN')\n"
                            ),
                        },
                        {
                            "name": "lib",
                            "isMain": False,
                            "content": "function helper() return 42 end\n",
                        },
                    ],
                }
            )
            return
        if path == "/api/quickApp":
            # the flua client decodes the base64 envelope and sends the raw
            # .fqa JSON body (the real HC3's upload contract)
            fqa = body if isinstance(body, dict) and isinstance(body.get("files"), list) else None
            if fqa is None:
                self._send_json({"error": "bad fqa"}, 400)
                return
            type(self).uploaded.append(fqa)
            self._send_json({"id": 300, "name": fqa["name"]})
            return
        if path in ("/api/plugins/updateProperty", "/api/plugins/interfaces"):
            self._send_json(None, 204)  # updateQA's property/interface sync
            return
        self._send_json({"error": "not found"}, 404)

    def do_PUT(self):
        body = self._read_body()
        path = self.path.split("?")[0]
        if path.startswith("/api/quickApp/") and path.endswith("/files"):
            qa_id = int(path.split("/")[3])
            type(self).file_updates.append((qa_id, body))
            self._send_json(None, 204)
            return
        if path.startswith("/api/devices/"):
            self._send_json(None, 204)  # name/enabled/visible updates (updateQA renames)
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
    _MockHc3.device_delay = 0.0
    _MockHc3.uploaded = []
    _MockHc3.file_updates = []
    _MockHc3.export_post_rejects = False
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
async def test_slow_remote_call_does_not_freeze_other_qas(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # QA a makes a SLOW remote api.get; QA b's interval keeps ticking while
    # a waits. The calling QA is suspended (its own messages defer), but the
    # pump and every other QA keep running — with the old blocking dispatch
    # b would tick zero times during a's ~0.8s call.
    _MockHc3.device_delay = 0.8
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    slow = tmp_path / "slow.lua"
    slow.write_text(
        "--%%name:slowpoke\n"
        "function QuickApp:onInit()\n"
        "  local d, status = api.get('/devices/45')\n"
        "  print('SLOW DONE', status, d.name)\n"
        "  exit(0)\n"
        "end\n"
    )
    tick = tmp_path / "tick.lua"
    tick.write_text(
        "--%%name:ticker\n"
        "local n = 0\n"
        "function QuickApp:onInit()\n"
        "  setInterval(function()\n"
        "    n = n + 1\n"
        "    print('TICK', n)\n"
        "  end, 100)\n"
        "end\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.start_qa(str(slow), None, {}, str(slow))
        engine.start_qa(str(tick), None, {}, str(tick))
        await asyncio.sleep(1.2)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "SLOW DONE 200 hc3-device" in out
    ticks = out.count("TICK ")
    assert ticks >= 3, f"other QA frozen during the remote call ({ticks} ticks): {out}"


@pytest.mark.asyncio
async def test_remote_api_call_suspends_only_calling_qa(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # while the slow call is in flight, messages for the CALLING QA defer
    # (the sleep machinery): its own timer fires only after the response
    # resumes the coroutine — and api.get returns the response values in
    # order, mid-callback
    _MockHc3.device_delay = 0.4
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    script = tmp_path / "seq.lua"
    script.write_text(
        "--%%name:sequenced\n"
        "function QuickApp:onInit()\n"
        "  local events = {}\n"
        "  setTimeout(function()\n"
        "    events[#events + 1] = 'timer'\n"
        "    print('ORDER', table.concat(events, ','))\n"
        "    exit(0)\n"
        "  end, 50)\n"
        "  local d, status = api.get('/devices/45')\n"
        "  events[#events + 1] = 'api:' .. status\n"
        "end\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(1.0)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "ORDER api:200,timer" in out  # the call completed before the deferred timer


@pytest.mark.asyncio
async def test_flua_mode_reports_effective_runtime_mode(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # _FLUA.mode: the effective runtime mode — online in a remote run,
    # offline for a QA that pinned itself offline, offline without a backend
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    online = tmp_path / "online.lua"
    online.write_text(
        "function QuickApp:onInit() print('MODE', _FLUA.mode); exit(0) end\n"
    )
    pinned = tmp_path / "pinned.lua"
    pinned.write_text(
        "--%%mode:offline\nfunction QuickApp:onInit() print('PINNED', _FLUA.mode); exit(0) end\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        # load_qa_file parses the --%% header (start_qa takes a raw config)
        assert engine.load_qa_file(str(online))[1] is None
        assert engine.load_qa_file(str(pinned))[1] is None
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "MODE online" in out
    assert "PINNED offline" in out


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
    device_requests = [r for r in _MockHc3.requests_seen if r.startswith("/api/devices")]
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
    # changes (the old bridge hack replaced by a message)
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


def test_cli_defaults_to_offline_even_with_hc3_env(tmp_path, mock_hc3) -> None:
    # no --api flag, no --%%mode: OFFLINE is the default — the sim answers,
    # the HC3 (even with credentials in the environment) is not consulted
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
    assert "mode offline" in result.stdout
    assert "MODE 404 nil" in result.stdout  # the sim has no device 45


def test_ctrl_c_terminates_promptly_mid_long_poll(tmp_path, mock_hc3) -> None:
    # Ctrl-C must not wait out a held refreshStates long poll: the request
    # runs on a daemon thread, so the process exits right away (code 130).
    # (Before the daemon thread, asyncio.run joined the abandoned executor
    # worker — exit waited out the mock's full 20s hold.)
    script = tmp_path / "keep.lua"
    script.write_text("--%%keep-alive:true\n--%%mode:online\nprint('KA')\n")
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


def test_cli_default_mode_is_offline(tmp_path, monkeypatch) -> None:
    # no --api flag and no --%%mode directive: OFFLINE is the default —
    # no HC3 credentials are needed (online is opt-in via --%%mode)
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
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mode offline" in result.stdout  # the sim is the default
    assert "x" in result.stdout


def test_cli_mode_online_directive_selects_hc3(tmp_path, mock_hc3) -> None:
    # --%%mode:online in the QA's header overrides the offline default —
    # the QA's api.* then talks to the real HC3
    script = tmp_path / "main.lua"
    script.write_text(
        "--%%mode:online\n"
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
    assert "mode online" in result.stdout
    assert "MODE 200 hc3-device" in result.stdout


@pytest.mark.asyncio
async def test_devices_list_is_union_of_sim_and_hc3(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # online: api.get('/devices') serves the UNION of the emulated QAs and
    # the HC3's devices — the developer feels at home on the controller.
    # An offline-pinned QA always sees the sim only.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mock_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    a = tmp_path / "a.lua"
    a.write_text(
        "setTimeout(function()\n"
        "  local ds = api.get('/devices')\n"
        "  print('A', #ds, ds[1].name, ds[2].name, ds[3].name)\n"
        "end, 20)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "--%%mode:offline\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function()\n"
        "  local ds = api.get('/devices')\n"
        "  print('B', #ds)\n"
        "end, 30)\n"
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
    # QA a + QA b + the sim's device 1 (the HC3) + the two HC3 devices
    assert "A 5" in out
    assert "hc3-device" in out and "hc3-other" in out
    assert "HC3" in out
    assert "B 3" in out  # the offline-pinned QA sees the sim only (1 + a + b)


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


# -- --tool/-t: HC3 file transfer tools ------------------------------------------


def _tool_project(tmp_path, name: str = "Proj") -> tuple[Path, Path]:
    main = tmp_path / "main.lua"
    main.write_text(
        f"--%%name:{name}\n"
        "--%%type:com.fibaro.binarySwitch\n"
        "--%%file:lib.lua,lib\n"
        "-- --------------- EOH ---------------\n"
        "print(helper())\n"
    )
    lib = tmp_path / "lib.lua"
    lib.write_text("function helper() return 42 end\n")
    return main, lib


def test_tool_download_qa_unpacks_to_directory(tmp_path, mock_hc3) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "downloadQA", "45", "-d", str(target)],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    main = (target / "downloaded_main_45.lua").read_text(encoding="utf-8")
    assert "--%%name:downloaded" in main
    assert "--%%file:downloaded_lib_45.lua,lib" in main
    assert "print('MAIN')" in main
    # the UI structures translate back to --%%u rows, with callback names
    assert (
        "--%%u:{{label='lbl',text='Status'},{button='goBtn',text='Go',onReleased='goNow'}}"
    ) in main
    assert (
        "--%%u:{slider='dim',text='Brightness',min='0',max='100',step='1',"
        "value='50',onChanged='dimChanged'}"
    ) in main
    # QuickApp variables roundtrip as --%%var lines
    assert "--%%var:speed='42'" in main
    # the QA's old --%% header is dropped (could be outdated)
    assert "--%%name:OLD" not in main
    assert "--%%mode:offline" not in main
    # extras are namespaced <name>_<file>_<id>.lua, so several downloads can
    # share a directory
    assert "function helper() return 42 end" in (
        target / "downloaded_lib_45.lua"
    ).read_text(encoding="utf-8")


def test_tool_download_qa_falls_back_to_get_export(tmp_path, mock_hc3) -> None:
    # some firmware 400s the export POST altogether; the tool falls back to
    # the deprecated-but-working GET
    _MockHc3.export_post_rejects = True
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "downloadQA", "45", "-d", str(target)],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "downloaded_main_45.lua").exists()
    assert (target / "downloaded_lib_45.lua").exists()  # fetched through the GET fallback


def test_tool_upload_qa_posts_packaged_fqa(tmp_path, mock_hc3) -> None:
    home = tmp_path / "home"
    home.mkdir()
    main, _lib = _tool_project(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "flua", "-t", "uploadQA", str(main), "--room", "7"],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "uploaded Proj — HC3 device id 300" in result.stdout
    assert len(_MockHc3.uploaded) == 1
    fqa = _MockHc3.uploaded[0]
    assert fqa["name"] == "Proj"
    assert fqa["type"] == "com.fibaro.binarySwitch"
    assert [f["name"] for f in fqa["files"]] == ["main", "lib"]
    assert "print(helper())" in fqa["files"][0]["content"]
    assert "function helper()" in fqa["files"][1]["content"]


def _downloaded_project(tmp_path, name: str = "downloaded", qa_id: int = 45) -> Path:
    # a downloadQA-shaped project: <name>_main_<id>.lua + namespaced extras
    main = tmp_path / f"{name}_main_{qa_id}.lua"
    main.write_text(
        f"--%%name:{name}\n"
        "--%%type:com.fibaro.binarySwitch\n"
        f"--%%file:{name}_lib_{qa_id}.lua,lib\n"
        "-- --------------- EOH ---------------\n"
        "print(helper())\n"
    )
    (tmp_path / f"{name}_lib_{qa_id}.lua").write_text(
        "function helper() return 42 end\n"
    )
    return main


def test_tool_upload_qa_updates_id_from_qualified_main(tmp_path, mock_hc3) -> None:
    # a downloaded <Name>_main_<id>.lua carries the HC3 id — uploadQA updates
    # that QA instead of creating a new one
    home = tmp_path / "home"
    home.mkdir()
    main = _downloaded_project(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "uploadQA", str(main)],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "updated QA 45 from downloaded (2 files" in result.stdout  # prefix: sync extras follow
    assert _MockHc3.uploaded == []  # no new QA was created
    assert len(_MockHc3.file_updates) == 1
    qa_id, files = _MockHc3.file_updates[0]
    assert qa_id == 45
    assert [f["name"] for f in files] == ["main", "lib"]


def test_tool_upload_qa_resolves_qa_name_in_cwd(tmp_path, mock_hc3) -> None:
    # a bare QA name finds <sanitized>_main_<id>.lua in the current directory
    home = tmp_path / "home"
    home.mkdir()
    _downloaded_project(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "uploadQA", "downloaded"],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=tmp_path,  # the project files live here
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "updated QA 45 from downloaded (2 files" in result.stdout  # prefix: sync extras follow
    assert len(_MockHc3.file_updates) == 1


def test_tool_update_qa_puts_all_files(tmp_path, mock_hc3) -> None:
    home = tmp_path / "home"
    home.mkdir()
    main, _lib = _tool_project(tmp_path, name="Upd")
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool=updateQA", "45", str(main)],
        env=_hc3_env(mock_hc3, str(home)),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "updated QA 45 (2 files)" in result.stdout
    assert len(_MockHc3.file_updates) == 1
    qa_id, files = _MockHc3.file_updates[0]
    assert qa_id == 45
    assert [f["name"] for f in files] == ["main", "lib"]
    assert files[0]["isMain"] is True and files[1]["isMain"] is False
    assert files[0]["type"] == "lua" and files[1]["type"] == "lua"


def test_tool_unknown_command(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "bogus"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "unknown tool" in result.stderr


def test_cli_tool_listing(tmp_path) -> None:
    # a bare --tool (or --tool help, or -t) lists the installed tools
    for args in (["--tool"], ["--tool", "help"], ["-t"]):
        result = subprocess.run(
            [sys.executable, "-m", "flua", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        for tool in ("downloadQA", "updateQA", "uploadQA"):
            assert tool in result.stdout
        assert "flua --tool <name> --help" in result.stdout
