"""Proxy mode (--%%proxy:true): mirror a QA onto the real HC3.

Tests run against a local mock HC3 (a threaded HTTP server), never a real
controller. The mock plays both sides: it answers the controller-side REST
calls (deploy/reuse/CONNECT/updateProperty/...) and, where a test needs it,
acts as the proxy posting actions/UI events back into the emulator's
callback server.
"""

import asyncio
import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402


class _MockHc3(BaseHTTPRequestHandler):
    """A tiny HC3 that understands exactly what proxy mode calls."""

    devices: dict[int, dict] = {}
    next_id: int = 100
    requests: list[tuple[str, str, object]] = []  # (method, path, body)
    refresh_events: list[dict] = []  # served on the next refreshStates poll
    uploaded: list[dict] = []  # decoded .fqa packages (POST /quickApp)

    def _send_json(self, data, status: int = 200) -> None:
        payload = json.dumps(data).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode()

    @classmethod
    def reset(cls) -> None:
        cls.devices = {}
        cls.next_id = 100
        cls.requests = []
        cls.refresh_events = []
        cls.uploaded = []

    @classmethod
    def seen(cls, method: str, path: str) -> list:
        return [r for r in cls.requests if r[0] == method and r[1] == path]

    # -- handlers ---------------------------------------------------------------

    def do_GET(self):
        path, _, query_string = self.path.partition("?")
        query = {}
        for pair in query_string.split("&"):
            if "=" in pair:
                key, _, value = pair.partition("=")
                query[unquote(key)] = unquote(value)
        type(self).requests.append((self.command, path, None))
        if path == "/api/refreshStates":
            now = int(time.time())
            events, type(self).refresh_events = type(self).refresh_events, []
            self._send_json(
                {
                    "status": "IDLE",
                    "last": 5,
                    "timestamp": now,
                    "timestampMillis": now * 1000,
                    "events": events,
                }
            )
            return
        if path == "/api/devices":
            name = query.get("name")
            found = [d for d in type(self).devices.values() if d["name"] == name]
            self._send_json(sorted(found, key=lambda d: d["id"]))
            return
        if path.startswith("/api/devices/"):
            device_id = int(path.rsplit("/", 1)[1])
            device = type(self).devices.get(device_id)
            if device is None:
                self._send_json({"error": "not found"}, 404)
                return
            self._send_json(device)
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        body = self._read_body()
        path = self.path.split("?")[0]
        type(self).requests.append((self.command, path, body))
        if path == "/api/quickApp":
            # the flua client decodes the base64 envelope and sends the raw
            # .fqa JSON body (same contract as the real HC3)
            fqa = body if isinstance(body, dict) and isinstance(body.get("files"), list) else None
            if fqa is None:
                self._send_json({"error": "bad fqa"}, 400)
                return
            type(self).uploaded.append(fqa)
            device_id = type(self).next_id
            type(self).next_id += 1
            device = {
                "id": device_id,
                "name": fqa["name"],
                "type": fqa["type"],
                "interfaces": list(fqa.get("initialInterfaces") or []) + ["quickApp"],
                "properties": dict(fqa.get("initialProperties") or {}),
                "parentId": 0,
            }
            type(self).devices[device_id] = device
            self._send_json(device)
            return
        if path.startswith("/api/devices/") and "/action/" in path:
            device_id = int(path.split("/")[3])
            if device_id not in type(self).devices:
                self._send_json({"error": "not found"}, 404)
                return
            self._send_json(None, 202)
            return
        if path == "/api/plugins/updateProperty":
            device_id = body.get("deviceId")
            # like the real HC3: the proxy device emits the property event
            now = int(time.time())
            type(self).refresh_events.append(
                {
                    "type": "DevicePropertyUpdatedEvent",
                    "created": now,
                    "createdMillis": now * 1000,
                    "sourceType": "system",
                    "sourceId": 0,
                    "objects": [{"objectType": "device", "objectId": device_id}],
                    "data": {
                        "id": device_id,
                        "name": body.get("propertyName"),
                        "newValue": body.get("value"),
                        "oldValue": None,
                    },
                }
            )
            self._send_json(None, 204)
            return
        if path == "/api/plugins/updateView":
            self._send_json(None, 204)
            return
        if path == "/api/plugins/createChildDevice":
            device_id = type(self).next_id
            type(self).next_id += 1
            child = {
                "id": device_id,
                "name": body["name"],
                "type": body["type"],
                "parentId": body["parentId"],
                "interfaces": body.get("initialInterfaces") or ["quickAppChild"],
                "properties": dict(body.get("initialProperties") or {}),
            }
            type(self).devices[device_id] = child
            self._send_json(child, 201)
            return
        if path == "/api/plugins/interfaces":
            self._send_json(None, 204)
            return
        if path == "/api/plugins/restart":
            self._send_json(None, 204)
            return
        if path.startswith("/api/plugins/") and "/variables" in path:
            self._send_json({"name": "x", "value": None}, 201)
            return
        self._send_json({"error": "not found"}, 404)

    def do_PUT(self):
        body = self._read_body()
        path = self.path.split("?")[0]
        type(self).requests.append((self.command, path, body))
        if path.startswith("/api/devices/"):
            device_id = int(path.rsplit("/", 1)[1])
            device = type(self).devices.get(device_id)
            if device is None:
                self._send_json({"error": "not found"}, 404)
                return
            device.update(body or {})
            self._send_json(None, 204)
            return
        if path.startswith("/api/plugins/") and "/variables" in path:
            self._send_json(None, 204)
            return
        self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        path = self.path.split("?")[0]
        type(self).requests.append((self.command, path, None))
        if path.startswith("/api/devices/"):
            device_id = int(path.rsplit("/", 1)[1])
            type(self).devices.pop(device_id, None)
            self._send_json(None, 204)
            return
        if path.startswith("/api/plugins/") and "/variables" in path:
            self._send_json(None, 204)
            return
        self._send_json({"error": "not found"}, 404)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def mock_hc3():
    _MockHc3.reset()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield url
    server.shutdown()
    server.server_close()


def add_existing_proxy(proxy_id: int, name: str, device_type: str) -> None:
    _MockHc3.devices[proxy_id] = {
        "id": proxy_id,
        "name": name,
        "type": device_type,
        "interfaces": ["quickApp"],
        "properties": {},
    }


PROXY_SCRIPT = """--%%name:sw
--%%proxy:true
--%%u:{button="btn",text="Go",onReleased="turnOn"}
-- --------------- EOH ---------------
function QuickApp:onInit()
  print("INIT", self.id, self.name)
  setTimeout(function() self:updateProperty("value", true) end, 20)
end
function QuickApp:turnOn(event)
  local name = type(event) == "table" and (event.elementName or "none") or tostring(event)
  print("TURNON", self.id, name)
end
"""


async def wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.01)


async def wait_for_output(capsys, needle: str, timeout: float = 5.0) -> str:
    """Accumulate stdout until ``needle`` appears (capsys reads consume)."""
    seen = ""
    deadline = time.monotonic() + timeout
    while needle not in seen:
        if time.monotonic() > deadline:
            raise AssertionError(f"{needle!r} not printed; saw: {seen}")
        seen += capsys.readouterr().out
        await asyncio.sleep(0.01)
    return seen


def set_hc3_env(monkeypatch, tmp_path, url: str) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", url)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")


def write_script(tmp_path, content: str = PROXY_SCRIPT) -> Path:
    script = tmp_path / "sw.lua"
    script.write_text(content)
    return script


@pytest.mark.asyncio
async def test_proxy_fresh_deploy_reuses_id_and_connects(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # no proxy on the HC3 -> flua uploads one, and the emulated QA runs
    # under the HC3-assigned id (plua caveat 2)
    set_hc3_env(monkeypatch, tmp_path, mock_hc3)
    script = write_script(tmp_path)
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        assert qa_id == 100  # the proxy's HC3 id, not an engine id
        # wait for the QA's updateProperty timer: proves boot + forwarding
        await wait_until(lambda: _MockHc3.seen("POST", "/api/plugins/updateProperty"))
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "INIT 100 sw" in out  # QA sees the proxy id, keeps its own name
    # the deployed package: name_Proxy, same type, the proxy Lua code
    assert len(_MockHc3.uploaded) == 1
    fqa = _MockHc3.uploaded[0]
    assert fqa["name"] == "sw_Proxy"
    assert fqa["type"] == "com.fibaro.binarySwitch"
    assert "actionHandler" in fqa["files"][0]["content"]
    assert fqa["initialProperties"]["viewLayout"]["$jason"]  # UI travels along
    assert fqa["initialProperties"]["useUiView"] is True  # fresh default
    # a fresh proxy gets its UI through initialProperties — no redundant PUT
    assert not _MockHc3.seen("PUT", "/api/devices/100")
    # the CONNECT action carries the emulator's ip:port
    connects = [
        r for r in _MockHc3.requests if r[0] == "POST" and r[1] == "/api/devices/100/action/CONNECT"
    ]
    assert connects, "proxy was never told where the emulator listens"
    args = connects[0][2]["args"]
    assert args and args[0]["ip"] and args[0]["port"] > 0


@pytest.mark.asyncio
async def test_proxy_update_property_forwarded_event_comes_from_hc3(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # Caveat 1: the emulator pushes updateProperty to the HC3 and does NOT
    # generate its own refresh event — the one event the feed holds is the
    # HC3 proxy's, mirrored through the poll
    set_hc3_env(monkeypatch, tmp_path, mock_hc3)
    script = write_script(tmp_path)
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        await wait_until(lambda: _MockHc3.seen("POST", "/api/plugins/updateProperty"))
        # wait for the HC3's event to come back through the poll
        await wait_until(
            lambda: any(
                entry.get("type") == "DevicePropertyUpdatedEvent"
                for _, entry in engine.api.state.events
            )
        )
        updates = _MockHc3.seen("POST", "/api/plugins/updateProperty")
        assert any(
            update[2] == {"deviceId": qa_id, "propertyName": "value", "value": True}
            for update in updates
        )
        # exactly ONE event for the change (the mirrored HC3 event) — a local
        # duplicate would make it two
        value_events = [
            entry
            for _, entry in engine.api.state.events
            if entry.get("type") == "DevicePropertyUpdatedEvent"
            and (entry.get("data") or {}).get("id") == qa_id
        ]
        assert len(value_events) == 1
        # the local mirror was updated immediately (and by the mirrored event)
        assert engine.api.state.devices[qa_id]["properties"]["value"] is True
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_proxy_existing_reused_and_wrong_type_replaced(
    tmp_path, mock_hc3, monkeypatch
) -> None:
    set_hc3_env(monkeypatch, tmp_path, mock_hc3)
    script = write_script(tmp_path)
    # a matching proxy already exists -> reused, no upload
    add_existing_proxy(57, "sw_Proxy", "com.fibaro.binarySwitch")
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        # the CONNECT rides the loop; wait for it before stopping the engine
        await wait_until(lambda: _MockHc3.seen("POST", "/api/devices/57/action/CONNECT"))
    finally:
        await engine.stop()
    assert qa_id == 57
    assert _MockHc3.uploaded == []
    assert _MockHc3.seen("POST", "/api/devices/57/action/CONNECT")
    # a proxy of the wrong type is deleted and replaced
    _MockHc3.reset()
    add_existing_proxy(57, "sw_Proxy", "com.fibaro.multilevelSwitch")
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
    finally:
        await engine.stop()
    assert qa_id == 100  # the fresh proxy's id
    assert _MockHc3.seen("DELETE", "/api/devices/57")
    assert len(_MockHc3.uploaded) == 1


@pytest.mark.asyncio
async def test_proxy_existing_gets_current_ui_synced(tmp_path, mock_hc3, monkeypatch) -> None:
    # reusing an existing proxy refreshes its UI properties: the user may
    # have edited the --%%u directives between runs
    set_hc3_env(monkeypatch, tmp_path, mock_hc3)
    script = write_script(tmp_path)  # declares button "btn"
    add_existing_proxy(57, "sw_Proxy", "com.fibaro.binarySwitch")
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        assert qa_id == 57
    finally:
        await engine.stop()
    puts = [r for r in _MockHc3.requests if r[0] == "PUT" and r[1] == "/api/devices/57"]
    assert puts, "the existing proxy's UI was not refreshed"
    properties = puts[0][2]["properties"]
    assert set(properties) == {"viewLayout", "uiView", "uiCallbacks"}
    # useUiView is not declared: the HC3's own setting is respected
    assert "useUiView" not in properties
    # the pushed UI reflects the CURRENT --%%u directives, not whatever the
    # proxy carried before
    assert properties["uiView"][0]["components"][0]["name"] == "btn"
    assert properties["uiCallbacks"][0]["name"] == "btn"
    assert properties["viewLayout"]["$jason"]


@pytest.mark.asyncio
async def test_proxy_use_ui_view_respects_hc3_unless_declared(
    tmp_path, mock_hc3, monkeypatch
) -> None:
    # an explicit --%%useUiView directive is pushed; without one, the proxy
    # keeps whatever the user configured on the HC3 (legacy viewLayout users)
    set_hc3_env(monkeypatch, tmp_path, mock_hc3)
    add_existing_proxy(57, "sw_Proxy", "com.fibaro.binarySwitch")
    script = write_script(tmp_path)
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        _qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
    finally:
        await engine.stop()
    puts = [r for r in _MockHc3.requests if r[0] == "PUT" and r[1] == "/api/devices/57"]
    assert puts and "useUiView" not in puts[0][2]["properties"]
    # now the QA declares the legacy view: the directive is pushed through
    _MockHc3.reset()
    add_existing_proxy(57, "sw_Proxy", "com.fibaro.binarySwitch")
    script.write_text(
        "--%%name:sw\n"
        "--%%proxy:true\n"
        "--%%useUiView:false\n"
        '--%%u:{button="btn",text="Go",onReleased="turnOn"}\n'
        "-- --------------- EOH ---------------\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        _qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
    finally:
        await engine.stop()
    puts = [r for r in _MockHc3.requests if r[0] == "PUT" and r[1] == "/api/devices/57"]
    assert puts and puts[0][2]["properties"]["useUiView"] is False


@pytest.mark.asyncio
async def test_proxy_duplicate_proxies_keep_newest(tmp_path, mock_hc3, monkeypatch) -> None:
    set_hc3_env(monkeypatch, tmp_path, mock_hc3)
    script = write_script(tmp_path)
    add_existing_proxy(56, "sw_Proxy", "com.fibaro.binarySwitch")
    add_existing_proxy(57, "sw_Proxy", "com.fibaro.binarySwitch")
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
    finally:
        await engine.stop()
    assert qa_id == 57  # newest wins
    assert _MockHc3.seen("DELETE", "/api/devices/56")
    assert _MockHc3.uploaded == []


@pytest.mark.asyncio
async def test_proxy_action_callback_runs_qa(tmp_path, capsys, mock_hc3, monkeypatch) -> None:
    # the HC3 proxy posts device actions back into the emulator's callback
    # server, which runs them through the QA's callAction
    set_hc3_env(monkeypatch, tmp_path, mock_hc3)
    script = write_script(tmp_path)
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        assert qa_id == 100
        # wait for CONNECT: proves the callback server bound (its real port
        # is only known after start())
        await wait_until(lambda: _MockHc3.seen("POST", "/api/devices/100/action/CONNECT"))
        server = engine._proxy_server
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/devices/{qa_id}/action/turnOn",
            data=json.dumps({"args": [42]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # a synchronous urlopen on the loop would deadlock the server
        with await asyncio.to_thread(urllib.request.urlopen, request, timeout=5) as response:
            assert response.status == 202
        out = await wait_for_output(capsys, "TURNON")
        assert "TURNON 100 42" in out  # the action args reached callAction
        # the action was already recorded by the real HC3: no local duplicate
        action_events = [
            entry
            for _, entry in engine.api.state.events
            if entry.get("type") == "DeviceActionRanEvent"
        ]
        assert action_events == []
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_proxy_ui_event_callback_runs_callback(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # the HC3 proxy posts UI events to /api/plugins/callUIEvent (JSON body)
    set_hc3_env(monkeypatch, tmp_path, mock_hc3)
    script = write_script(tmp_path)
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        await wait_until(lambda: _MockHc3.seen("POST", "/api/devices/100/action/CONNECT"))
        server = engine._proxy_server
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/plugins/callUIEvent",
            data=json.dumps(
                {"deviceID": qa_id, "eventType": "onReleased", "elementName": "btn"}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with await asyncio.to_thread(urllib.request.urlopen, request, timeout=5) as response:
            assert response.status == 200
        out = await wait_for_output(capsys, "TURNON")
        assert "TURNON 100 btn" in out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_proxy_create_child_device_uses_hc3_id(
    tmp_path, capsys, mock_hc3, monkeypatch
) -> None:
    # children of a proxy QA are created on the HC3 and shadowed under the
    # HC3-assigned id
    script = tmp_path / "kids.lua"
    script.write_text(
        "--%%name:kids\n--%%proxy:true\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  local child = self:createChildDevice({name='c', type='com.fibaro.binarySwitch'})\n"
        "  print('CHILD', child.id, child.name)\n"
        "end\n"
    )
    set_hc3_env(monkeypatch, tmp_path, mock_hc3)
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        assert qa_id == 100
        out = await wait_for_output(capsys, "CHILD")
        assert "CHILD 101 c" in out  # the HC3-assigned id, not a sim id
        assert _MockHc3.seen("POST", "/api/plugins/createChildDevice")
        assert engine.api.state.devices[101]["parentId"] == 100
        assert engine.api.state.is_proxy(101)
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_proxy_offline_is_disabled_with_warning(
    tmp_path, capsys, caplog, monkeypatch
) -> None:
    # proxy mode only works online: offline it degrades to a plain QA with a
    # warning and never touches an HC3
    script = write_script(tmp_path)
    engine = LuaEngine()  # api_mode local: no HC3
    await engine.start()
    try:
        qa_id = engine.start_qa(str(script), None, {"proxy": True}, str(script))
        assert qa_id == 5000  # engine id: no proxy involved
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    assert "proxy disabled" in caplog.text
    assert not engine.api.state.is_proxy(qa_id)
    assert capsys.readouterr().out  # the QA still ran normally
