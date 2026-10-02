"""Offline HC3 REST API: routing, simulated state, and the Lua bridge.

Unit tests drive Api.dispatch directly (no Lua, no asyncio); integration
tests run QAs against the API through the engine, and a CLI test covers
``--seed`` end to end.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.api import Api
from flua.api.state import FIRST_RUNTIME_ID
from flua.engine import LuaEngine

REPO_ROOT = Path(__file__).resolve().parent.parent

SEED = {
    "devices": [
        {
            "id": 10,
            "name": "lamp",
            "type": "com.fibaro.binarySwitch",
            "properties": {"value": False},
            "roomID": 1,
        },
        {
            "id": 20,
            "name": "motion",
            "type": "com.fibaro.binarySensor",
            "properties": {"value": False},
            "parentId": 10,
        },
    ],
    "rooms": [{"id": 1, "name": "Living Room"}],
    "scenes": [{"id": 5, "name": "Evening"}],
    "globalVariables": {"night": {"value": "false"}, "plain": "hello"},
}


@pytest.fixture
def api() -> Api:
    return Api(seed=SEED)


# -- devices ----------------------------------------------------------------


def test_devices_list(api: Api) -> None:
    data, status = api.dispatch("GET", "/devices")
    assert status == 200
    assert [d["id"] for d in data] == [1, 10, 20]  # the HC3 + the seed


def test_devices_query_filters(api: Api) -> None:
    data, status = api.dispatch("GET", "/devices?type=com.fibaro.binarySensor")
    assert status == 200 and [d["id"] for d in data] == [20]

    data, _ = api.dispatch("GET", "/devices?parentId=10")
    assert [d["id"] for d in data] == [20]

    data, _ = api.dispatch("GET", "/devices?visible=false")
    assert data == []

    data, _ = api.dispatch("GET", "/devices?roomID=1")
    assert [d["id"] for d in data] == [10]


def test_devices_query_interface_sees_qa_devices(api: Api) -> None:
    api.register_qa(5000, "qa", None, {"value": True})
    data, status = api.dispatch("GET", "/devices?interface=quickApp")
    assert status == 200 and [d["id"] for d in data] == [5000]


def test_device_get_and_missing(api: Api) -> None:
    data, status = api.dispatch("GET", "/devices/10")
    assert status == 200
    assert data["name"] == "lamp"
    assert data["properties"]["value"] is False
    assert api.dispatch("GET", "/devices/99") == (None, 404)
    assert api.dispatch("GET", "/devices/abc") == (None, 404)


def test_device_update(api: Api) -> None:
    assert api.dispatch("PUT", "/devices/10", {"name": "lamp2", "visible": False}) == (
        None,
        204,
    )
    data, _ = api.dispatch("GET", "/devices/10")
    assert data["name"] == "lamp2"
    assert data["visible"] is False
    assert api.dispatch("PUT", "/devices/99", {"name": "x"}) == (None, 404)


def test_device_delete(api: Api) -> None:
    assert api.dispatch("DELETE", "/devices/20") == (None, 204)
    assert api.dispatch("GET", "/devices/20") == (None, 404)
    assert api.dispatch("DELETE", "/devices/20") == (None, 404)


def test_device_property_get(api: Api) -> None:
    assert api.dispatch("GET", "/devices/10/properties/value") == (False, 200)
    assert api.dispatch("GET", "/devices/10/properties/nope") == (None, 404)
    assert api.dispatch("GET", "/devices/99/properties/value") == (None, 404)


def test_responses_are_copies(api: Api) -> None:
    data, _ = api.dispatch("GET", "/devices/10")
    data["properties"]["value"] = True
    again, _ = api.dispatch("GET", "/devices/10")
    assert again["properties"]["value"] is False


# -- plugins ------------------------------------------------------------------


def test_variables_status_contract(api: Api) -> None:
    api.register_qa(5000, "qa", None, {})
    # PUT on a missing variable -> 404 (quickapp.lua then POSTs to create it)
    assert api.dispatch("PUT", "/plugins/5000/variables/k", {"name": "k", "value": "v"}) == (
        None,
        404,
    )
    var, status = api.dispatch("POST", "/plugins/5000/variables", {"name": "k", "value": "v"})
    assert status == 201 and var["name"] == "k" and var["value"] == "v"
    assert api.dispatch(
        "PUT", "/plugins/5000/variables/k", {"name": "k", "value": "v2", "isHidden": True}
    ) == (None, 204)
    var, status = api.dispatch("GET", "/plugins/5000/variables/k")
    assert status == 200 and var["value"] == "v2" and var["isHidden"] is True
    assert api.dispatch("DELETE", "/plugins/5000/variables/k") == (None, 204)
    assert api.dispatch("GET", "/plugins/5000/variables/k") == (None, 404)


def test_variables_list_and_clear(api: Api) -> None:
    api.register_qa(5000, "qa", None, {})
    api.dispatch("POST", "/plugins/5000/variables", {"name": "b", "value": "2"})
    api.dispatch("POST", "/plugins/5000/variables", {"name": "a", "value": "1"})
    data, status = api.dispatch("GET", "/plugins/5000/variables")
    assert status == 200 and [v["name"] for v in data] == ["a", "b"]
    assert api.dispatch("DELETE", "/plugins/5000/variables") == (None, 204)
    assert api.dispatch("GET", "/plugins/5000/variables") == ([], 200)


def test_plugin_routes_reject_non_plugins(api: Api) -> None:
    assert api.dispatch("GET", "/plugins/10") == (None, 404)
    assert api.dispatch("GET", "/plugins/99/variables") == (None, 404)
    # variables serve any existing device (empty for non-QAs — dev/apitest
    # reads them on device 1), but unknown devices still 404
    data, status = api.dispatch("GET", "/plugins/10/variables")
    assert status == 200 and data == []
    api.register_qa(5000, "qa", None, {})
    data, status = api.dispatch("GET", "/plugins/5000")
    assert status == 200 and data["name"] == "qa"


def test_create_child_device(api: Api) -> None:
    api.register_qa(5000, "qa", None, {})
    child, status = api.dispatch(
        "POST",
        "/plugins/createChildDevice",
        {
            "name": "light",
            "type": "com.fibaro.binarySwitch",
            "parentId": 5000,
            "initialProperties": {"value": False},
            "initialInterfaces": ["light"],
        },
    )
    assert status == 201
    assert child["id"] >= FIRST_RUNTIME_ID
    assert child["parentId"] == 5000
    assert child["properties"]["value"] is False
    assert child["interfaces"] == ["light"]
    children, _ = api.dispatch("GET", "/devices?parentId=5000")
    assert [d["id"] for d in children] == [child["id"]]
    # unknown parent
    assert api.dispatch("POST", "/plugins/createChildDevice", {"name": "x", "parentId": 9999}) == (
        None,
        404,
    )


def test_update_property(api: Api) -> None:
    api.register_qa(5000, "qa", None, {})
    assert api.dispatch(
        "POST",
        "/plugins/updateProperty",
        {"deviceId": 5000, "propertyName": "value", "value": True},
    ) == (None, 204)
    data, _ = api.dispatch("GET", "/devices/5000")
    assert data["properties"]["value"] is True
    assert api.dispatch(
        "POST", "/plugins/updateProperty", {"deviceId": 9999, "propertyName": "v", "value": 1}
    ) == (None, 404)


def test_update_view(api: Api) -> None:
    api.register_qa(5000, "qa", None, {})
    assert api.dispatch(
        "POST",
        "/plugins/updateView",
        {"deviceId": 5000, "componentName": "btn", "propertyName": "text", "newValue": "on"},
    ) == (None, 204)
    data, _ = api.dispatch("GET", "/devices/5000")
    assert data["view"]["btn"]["text"] == "on"


def test_update_interfaces(api: Api) -> None:
    api.register_qa(5000, "qa", None, {})
    assert api.dispatch(
        "POST", "/plugins/interfaces", {"action": "add", "deviceId": 5000, "interfaces": ["power"]}
    ) == (None, 204)
    data, _ = api.dispatch("GET", "/devices/5000")
    assert "power" in data["interfaces"]
    assert api.dispatch(
        "POST",
        "/plugins/interfaces",
        {"action": "remove", "deviceId": 5000, "interfaces": ["power"]},
    ) == (None, 204)
    data, _ = api.dispatch("GET", "/devices/5000")
    assert "power" not in data["interfaces"]


def test_plugin_restart_is_simulated(api: Api) -> None:
    assert api.dispatch("POST", "/plugins/restart", {"deviceId": 10}) == (None, 204)


# -- system -------------------------------------------------------------------


def test_global_variables(api: Api) -> None:
    data, status = api.dispatch("GET", "/globalVariables/night")
    assert status == 200 and data["value"] == "false"
    assert api.dispatch("GET", "/globalVariables/missing") == (None, 404)
    var, status = api.dispatch(
        "PUT", "/globalVariables/night", {"value": True, "invokeScenes": True}
    )
    assert status == 200 and var["value"] == "True"
    # the real HC3 404s a PUT on a missing variable — create is a POST
    assert api.dispatch("PUT", "/globalVariables/new", {"value": 42}) == (None, 404)
    data, _ = api.dispatch("GET", "/globalVariables")
    assert [v["name"] for v in data] == ["night", "plain"]


def test_global_variable_create(api: Api) -> None:
    # POST /globalVariables — the real HC3's create call (the body carries
    # the name; a nameless body is a bad request)
    var, status = api.dispatch("POST", "/globalVariables", {"name": "FLUA", "value": "1"})
    assert status == 200
    assert var["name"] == "FLUA" and var["value"] == "1"
    assert abs(var["modified"] - int(time.time())) <= 2  # stamped with now
    got, status = api.dispatch("GET", "/globalVariables/FLUA")
    assert status == 200 and got["value"] == "1"
    assert api.dispatch("POST", "/globalVariables", {"value": "1"})[1] == 400
    # creating over an existing variable is a conflict — and the value stays
    assert api.dispatch("POST", "/globalVariables", {"name": "FLUA", "value": "2"})[1] == 409
    got, _ = api.dispatch("GET", "/globalVariables/FLUA")
    assert got["value"] == "1"
    data, _ = api.dispatch("GET", "/globalVariables")
    assert [v["name"] for v in data] == ["FLUA", "night", "plain"]


def test_global_variable_events(api: Api) -> None:
    # create/change/delete emit the corresponding refreshStates events (the
    # real HC3's GlobalVariableAdded/Changed/RemovedEvent shapes) — and an
    # unchanged PUT stays silent, like device property events
    api.dispatch("POST", "/globalVariables", {"name": "GV", "value": "1"})
    api.dispatch("PUT", "/globalVariables/GV", {"value": "2"})
    api.dispatch("PUT", "/globalVariables/GV", {"value": "2"})  # no change
    assert api.dispatch("DELETE", "/globalVariables/missing")[1] == 404
    api.dispatch("DELETE", "/globalVariables/GV")
    events = [entry for _, entry in api.state.events]
    assert [e["type"] for e in events] == [
        "GlobalVariableAddedEvent",
        "GlobalVariableChangedEvent",
        "GlobalVariableRemovedEvent",
    ]
    assert events[0]["data"] == {"variableName": "GV", "value": "1"}
    assert events[1]["data"] == {"variableName": "GV", "oldValue": "1", "newValue": "2"}
    assert events[2]["data"] == {"variableName": "GV"}
    for entry in events:
        # the lighter global-event envelope: no objects/sourceId
        assert entry["sourceType"] == "system"
        assert "objects" not in entry and "sourceId" not in entry


@pytest.mark.asyncio
async def test_global_variable_events_reach_subscribers(tmp_path, capsys) -> None:
    # the events ride the pump: a RefreshStateSubscriber sees them
    script = tmp_path / "gv.lua"
    script.write_text(
        "local sub = RefreshStateSubscriber()\n"
        "sub:subscribe(function(e) return true end, "
        "function(e) print('EV', e.type, e.data and e.data.variableName) end)\n"
        "sub:run()\n"
        "function QuickApp:onInit()\n"
        "  api.post('/globalVariables', {name='SUBGV', value='0'})\n"
        "  fibaro.setGlobalVariable('SUBGV', 'x')\n"
        "  fibaro.setGlobalVariable('SUBGV', 'y')\n"
        "  fibaro.deleteGlobalVariable('SUBGV')\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.3)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "EV GlobalVariableChangedEvent SUBGV" in out
    assert "EV GlobalVariableRemovedEvent SUBGV" in out


@pytest.mark.asyncio
async def test_warn_directive_logs_api_error_codes(tmp_path, capsys) -> None:
    # --%%warn:true: api error codes are easy to ignore — the emulator logs
    # them so the developer notices
    script = tmp_path / "w.lua"
    script.write_text(
        "--%%warn:true\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  api.get('/notAnEndpoint')\n"
        "  api.post('/alsoMissing', {name='x'})\n"
        "  print('DONE')\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        await asyncio.sleep(0.3)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    # flua's own format: a [FLUA] level column + the QA tag (name+id)
    assert "api GET /notAnEndpoint -> 404" in out
    assert "[FLUA" in out and "[w5000]" in out
    assert "api POST /alsoMissing -> 404" in out
    assert "DONE" in out  # warnings don't stop the QA


@pytest.mark.asyncio
async def test_warn_directive_off_by_default(tmp_path, capsys) -> None:
    # without --%%warn the error codes stay silent, like on the HC3
    script = tmp_path / "w.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  api.get('/notAnEndpoint')\n"
        "  print('DONE')\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.3)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "-> 404" not in out
    assert "DONE" in out


@pytest.mark.asyncio
async def test_print_of_api_error_shows_status(tmp_path, capsys) -> None:
    # print(api.post(...)) on an unknown endpoint returns (nil, status); a nil
    # first arg must not blank the QA log message (logStr used to drop it)
    script = tmp_path / "p.lua"
    script.write_text(
        "print(api.post('/notAnEndpoint', {name='FLUA', value='1'}))\n"
        "print(api.post('/globalVariables', {name='FLUA', value='1'}))\n"
        "local v = api.get('/globalVariables/FLUA')\n"
        "print('MOD', v.modified == os.time())\n"  # stamped with virtual now
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "nil 404" in out  # the error status is visible, not blanked
    assert " 200" in out  # the create call's status prints beside the table
    assert "MOD true" in out  # modified == os.time() (the virtual clock)


def test_rooms(api: Api) -> None:
    data, status = api.dispatch("GET", "/rooms")
    assert status == 200 and data[0]["name"] == "Living Room"
    room, status = api.dispatch("GET", "/rooms/1")
    assert status == 200 and room["id"] == 1
    # the HC3 always has the default room, id 219
    default, status = api.dispatch("GET", "/rooms/219")
    assert status == 200 and default["name"] == "Default room"
    assert default["sectionID"] == 219
    assert any(r["id"] == 219 for r in data)
    # and the default section, also 219 — rooms without an explicit section
    # land there (the seeded Living Room has no sectionID)
    sections, status = api.dispatch("GET", "/sections")
    assert status == 200
    assert any(s["id"] == 219 and s["name"] == "Default section" for s in sections)
    section, status = api.dispatch("GET", "/sections/219")
    assert status == 200 and section["id"] == 219
    assert room.get("sectionID") == 219
    assert api.dispatch("GET", "/rooms/99") == (None, 404)


# -- routing --------------------------------------------------------------------


def test_unknown_paths_are_404(api: Api) -> None:
    assert api.dispatch("GET", "/energy/consumption/summary") == (None, 404)  # M3
    assert api.dispatch("PATCH", "/devices/10") == (None, 404)
    assert api.dispatch("GET", "/no/such/endpoint") == (None, 404)


# -- integration: QAs through the engine ---------------------------------------


@pytest.mark.asyncio
async def test_qa_uses_api_offline(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "local MYID\n"
        "function QuickApp:onInit()\n"
        "  MYID = self.id\n"
        "  self:internalStorageSet('k', 'v', false)\n"
        "end\n"
        "setTimeout(function()\n"
        "  local var = api.get('/plugins/'..MYID..'/variables/k')\n"
        "  print('VAR', var.value, fibaro.getGlobalVariable('night'))\n"
        "end, 20)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "setTimeout(function()\n"
        "  local dev = api.get('/devices/5000')\n"
        "  print('DEV', dev.name)\n"
        "end, 30)\n"
    )
    engine = LuaEngine(seed=SEED)
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        engine.start_qa(str(b), None, {}, str(b))
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "VAR v false" in out
    assert "DEV a" in out


def test_cli_seed_offline(tmp_path) -> None:
    script = tmp_path / "gv.lua"
    script.write_text("print('GV', fibaro.getGlobalVariable('night'))\n")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"globalVariables": {"night": "false"}}))
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "--seed", str(seed), str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GV false" in result.stdout


def test_cli_api_remote_rejected(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "remote", "-e", "exit(0)"],
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


# -- M2: actions, events, scenes, alarms, refreshStates, profiles ---------------


def test_device_action_emits(api: Api) -> None:
    api.register_qa(5000, "qa", None, {})
    assert api.dispatch("POST", "/devices/5000/action/turnOn", {"args": [1, 2]}) == (None, 202)
    assert api.emitted[0] == {
        "type": "deviceAction",
        "id": 5000,
        "action": "turnOn",
        "args": [1, 2],
    }
    assert api.emitted[1]["type"] == "refreshStateEvent"
    assert api.emitted[1]["event"]["type"] == "DeviceActionRanEvent"


def test_device_action_without_args(api: Api) -> None:
    api.register_qa(5000, "qa", None, {})
    assert api.dispatch("POST", "/devices/5000/action/setValue") == (None, 202)
    assert api.emitted[0]["args"] == []


def test_device_action_missing_device(api: Api) -> None:
    assert api.dispatch("POST", "/devices/99/action/turnOn", {}) == (None, 404)
    assert api.emitted == []


def test_group_action(api: Api) -> None:
    api.register_qa(5000, "a", None, {})
    api.register_qa(5001, "b", None, {})
    data, status = api.dispatch(
        "POST", "/devices/groupAction/setValue", {"devices": [5000, 5001, 9999], "args": [True]}
    )
    assert status == 202
    assert data == {"devices": [5000, 5001]}
    actions = [m for m in api.emitted if m["type"] == "deviceAction"]
    assert [m["id"] for m in actions] == [5000, 5001]


def test_custom_event(api: Api) -> None:
    assert api.dispatch("POST", "/customEvents/wakeup") == (None, 202)
    assert api.emitted == [{"type": "customEvent", "name": "wakeup"}]
    assert api.state.custom_events == [{"name": "wakeup"}]
    data, _ = api.dispatch("GET", "/refreshStates")
    assert data["events"] == [{"type": "CustomEvent", "data": {"name": "wakeup"}}]


def test_misc_system_endpoints(api: Api) -> None:
    # the GET endpoints dev/apitest.lua exercises — empty results are fine
    assert api.dispatch("POST", "/customEvents", {"name": "testEvent", "userDescription": "x"})[
        1
    ] < 206
    for url in (
        "/customEvents",
        "/customEvents/testEvent",
        "/iosDevices",
        "/home",
        "/debugMessages",
        "/weather",
        "/alarms/v1/devices",
        "/notificationCenter",
        "/profiles/1",
        "/icons",
        "/users",
        "/energy/devices",
        "/panels/location",
        "/panels/climate",
        "/panels/climate/1",
        "/panels/notifications",
        "/panels/family",
        "/panels/sprinklers",
        "/panels/humidity",
        "/panels/favoriteColors",
        "/panels/favoriteColors/v2",
        "/diagnostics",
        "/settings/info",
        "/plugins/1/variables",
    ):
        _data, status = api.dispatch("GET", url)
        assert status < 206, f"{url} -> {status}"
    # shapes worth pinning
    home, _ = api.dispatch("GET", "/home")
    assert home["hcName"] == "HC3"
    info, _ = api.dispatch("GET", "/settings/info")
    assert info["defaultRoomId"] == 219
    assert info["sunsetHour"].count(":") == 1
    users, _ = api.dispatch("GET", "/users")
    assert users[0]["name"] == "admin"


class _ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = b"hello-from-proxy"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def test_proxy_fetch() -> None:
    # GET /proxy?url=... fetches server-side through the engine's HTTP client
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProxyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        engine = LuaEngine()
        url = f"http://127.0.0.1:{server.server_port}/anything"
        body, status = engine.api.dispatch("GET", f"/proxy?url={url}")
        assert status == 200 and body == "hello-from-proxy"
        assert engine.api.dispatch("GET", "/proxy") == (None, 400)  # url required
    finally:
        server.shutdown()



def test_call_ui_event(api: Api) -> None:
    # GET /plugins/callUIEvent (the real HC3 endpoint): query-param driven
    # UI interaction delivered to the QA as a uiEvent message
    url = "/plugins/callUIEvent?deviceID=5000&elementName=B1&eventType=onReleased&value=42"
    assert api.dispatch("GET", url) == (None, 200)
    assert api.emitted == [
        {
            "type": "uiEvent",
            "deviceId": 5000,
            "elementName": "B1",
            "eventType": "onReleased",
            "value": "42",
        }
    ]
    # value is optional; deviceID/elementName/eventType are required
    api.emitted.clear()
    url = "/plugins/callUIEvent?deviceID=5000&elementName=B1&eventType=onReleased"
    assert api.dispatch("GET", url) == (None, 200)
    assert api.emitted == [
        {"type": "uiEvent", "deviceId": 5000, "elementName": "B1", "eventType": "onReleased"}
    ]
    assert api.dispatch("GET", "/plugins/callUIEvent?deviceID=5000") == (None, 400)
    assert api.dispatch(
        "GET", "/plugins/callUIEvent?deviceID=abc&elementName=B1&eventType=onReleased"
    ) == (None, 400)
    assert api.emitted == [
        {"type": "uiEvent", "deviceId": 5000, "elementName": "B1", "eventType": "onReleased"}
    ]


def test_scenes(api: Api) -> None:
    data, status = api.dispatch("GET", "/scenes")
    assert status == 200
    assert data[0]["name"] == "Evening"
    assert data[0]["running"] is False
    scene, status = api.dispatch("GET", "/scenes/5")
    assert status == 200 and scene["id"] == 5
    assert api.dispatch("POST", "/scenes/5/execute") == (None, 202)
    scene, _ = api.dispatch("GET", "/scenes/5")
    assert scene["running"] is True
    assert api.dispatch("POST", "/scenes/5/kill") == (None, 202)
    scene, _ = api.dispatch("GET", "/scenes/5")
    assert scene["running"] is False
    assert api.dispatch("POST", "/scenes/99/execute") == (None, 404)


def test_alarms_default_partition(api: Api) -> None:
    data, status = api.dispatch("GET", "/alarms/v1/partitions")
    assert status == 200 and [p["id"] for p in data] == [1]
    assert data[0]["armed"] is False
    assert api.dispatch("POST", "/alarms/v1/partitions/1/actions/arm") == (None, 202)
    part, _ = api.dispatch("GET", "/alarms/v1/partitions/1")
    assert part["armed"] is True
    assert api.dispatch("DELETE", "/alarms/v1/partitions/1/actions/disarm") == (None, 202)
    part, _ = api.dispatch("GET", "/alarms/v1/partitions/1")
    assert part["armed"] is False
    assert api.dispatch("POST", "/alarms/v1/partitions/actions/arm") == (None, 202)
    part, _ = api.dispatch("GET", "/alarms/v1/partitions/1")
    assert part["armed"] is True
    assert api.dispatch("DELETE", "/alarms/v1/partitions/actions/disarm") == (None, 202)
    assert api.dispatch("POST", "/alarms/v1/partitions/99/actions/arm") == (None, 404)
    data, _ = api.dispatch("GET", "/alarms/v1/partitions/breached")
    assert data == []


def test_alarms_breached_from_seed() -> None:
    api = Api(seed={"alarms": [{"id": 3, "name": "Garage", "armed": True, "breached": True}]})
    data, status = api.dispatch("GET", "/alarms/v1/partitions/breached")
    assert status == 200 and [p["id"] for p in data] == [3]


def test_refresh_states(api: Api) -> None:
    api.register_qa(5000, "qa", None, {})
    assert api.dispatch(
        "POST",
        "/plugins/updateProperty",
        {"deviceId": 5000, "propertyName": "value", "value": True},
    ) == (None, 204)
    data, status = api.dispatch("GET", "/refreshStates")
    assert status == 200
    assert data["last"] == 1
    assert data["status"] == "IDLE"  # the real HC3's idle base shape
    assert isinstance(data["date"], str) and isinstance(data["timestamp"], int)
    assert isinstance(data["timestampMillis"], int)
    # state updates are EVENTS on the real HC3 (changes is UI noise)
    assert "changes" not in data
    events = data["events"]
    assert len(events) == 1
    assert events[0]["type"] == "DevicePropertyUpdatedEvent"
    assert events[0]["sourceType"] == "system"
    assert events[0]["objects"] == [{"objectType": "device", "objectId": 5000}]
    assert events[0]["data"] == {
        "id": 5000,
        "property": "value",
        "newValue": True,
        "oldValue": False,
    }
    assert isinstance(events[0]["created"], int) and isinstance(events[0]["createdMillis"], int)
    # the same value again: no state change, no event (the user's rule)
    api.dispatch(
        "POST",
        "/plugins/updateProperty",
        {"deviceId": 5000, "propertyName": "value", "value": True},
    )
    data, _ = api.dispatch("GET", "/refreshStates?last=1")
    assert "events" not in data
    data, _ = api.dispatch("GET", "/refreshStates?last=1")
    assert "changes" not in data and "events" not in data  # nothing new: absent
    api.dispatch("POST", "/customEvents/x")
    data, _ = api.dispatch("GET", "/refreshStates?last=1")
    assert data["last"] == 2
    assert data["events"] == [{"type": "CustomEvent", "data": {"name": "x"}}]
    assert api.dispatch("GET", "/refreshStates?last=abc") == (None, 400)
    # configuration updates (name etc.) are the "changes" feed
    api.dispatch("PUT", "/devices/5000", {"name": "renamed"})
    data, _ = api.dispatch("GET", "/refreshStates?last=2")
    assert data["changes"] == [
        {"id": 5000, "name": "name", "newValue": "renamed", "oldValue": "qa"}
    ]


def test_profiles(api: Api) -> None:
    data, status = api.dispatch("GET", "/profiles")
    assert status == 200 and data[0]["id"] == 1 and data[0]["active"] is True
    assert api.dispatch("POST", "/profiles/activeProfile/1") == (None, 202)
    assert api.dispatch("POST", "/profiles/activeProfile/99") == (None, 404)


@pytest.mark.asyncio
async def test_qa_actions_and_events_offline(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "setTimeout(function()\n"
        "  fibaro.call(5001, 'turnOn')\n"
        "  fibaro.callGroupAction('setValue', {devices = {5001}, args = {true}})\n"
        "  fibaro.emitCustomEvent('wakeup')\n"
        "  local rs = api.get('/refreshStates')\n"
        "  print('RS', type(rs.last) == 'number' and rs.last >= 1)\n"
        "end, 20)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "function QuickApp:turnOn() print('B ON') end\n"
        "function QuickApp:setValue(v) self:updateProperty('value', v); print('B SET', v) end\n"
        "function QuickApp:onCustomEvent(name) print('CE', name) end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        engine.start_qa(str(b), None, {}, str(b))
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "B ON" in out
    assert "B SET true" in out
    assert "CE wakeup" in out
    assert "RS true" in out
