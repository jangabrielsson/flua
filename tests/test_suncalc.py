"""Device 1 (the HC3): sun times on the virtual clock + /settings/location."""

import asyncio
import json
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("lupa")

from flua.api import Api  # noqa: E402
from flua.engine import LuaEngine  # noqa: E402
from flua.suncalc import sunrise_sunset  # noqa: E402

HH_MM = re.compile(r"^\d{2}:\d{2}$")


class _MiniHc3(BaseHTTPRequestHandler):
    """Idle refreshStates feed plus an HC3 device 1 with fake sun values."""

    def _send(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith("/api/refreshStates"):
            self._send({"status": "IDLE", "last": 0, "events": [], "changes": []})
            return
        if self.path.startswith("/api/devices/1"):
            self._send(
                {
                    "id": 1,
                    "name": "mock-hc3",
                    "type": "HC3",
                    "properties": {"sunriseHour": "88:88", "sunsetHour": "99:99"},
                }
            )
            return
        self._send({}, 404)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def mini_hc3():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MiniHc3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_suncalc_stockholm_summer() -> None:
    # midsummer in Stockholm: a long day, sunrise well before sunset
    ts = datetime(2026, 6, 21, 12, 0).timestamp()
    sunrise, sunset, rise_t, set_t = sunrise_sunset(59.3293, 18.0686, ts)
    assert HH_MM.match(sunrise) and HH_MM.match(sunset)
    assert sunrise < sunset
    assert sunrise < "12:00" < sunset
    # civil twilight widens the day
    assert rise_t <= sunrise and set_t >= sunset


def test_suncalc_winter_night_still_formats() -> None:
    ts = datetime(2026, 12, 21, 12, 0).timestamp()
    sunrise, sunset, _r, _s = sunrise_sunset(59.3293, 18.0686, ts)
    assert HH_MM.match(sunrise) and HH_MM.match(sunset)
    assert sunrise < sunset


def test_suncalc_polar_variants_do_not_crash() -> None:
    # high latitudes: the sun may never rise/set — the algorithm returns 00:00
    ts = datetime(2026, 6, 21, 12, 0).timestamp()
    for lat in (-90.0, 90.0, 69.65, 0.0):
        values = sunrise_sunset(lat, 18.0, ts)
        assert all(HH_MM.match(v) for v in values)


def test_hc3_device_one_lists_and_gets() -> None:
    api = Api()
    devs, status = api.dispatch("GET", "/devices", None)
    assert status == 200
    dev1 = next(d for d in devs if d["id"] == 1)
    assert dev1["name"] == "HC3"
    assert HH_MM.match(dev1["properties"]["sunriseHour"])
    assert HH_MM.match(dev1["properties"]["sunsetHour"])


def test_settings_location_roundtrip() -> None:
    api = Api()
    loc, status = api.dispatch("GET", "/settings/location", None)
    assert status == 200 and loc["latitude"] == 59.3293  # the default
    assert api.dispatch(
        "PUT", "/settings/location", {"latitude": 1.5, "longitude": 2.5}
    ) == (None, 200)
    loc, status = api.dispatch("GET", "/settings/location", None)
    assert loc["latitude"] == 1.5 and loc["longitude"] == 2.5


def test_location_seeded_and_persisted(tmp_path) -> None:
    db = tmp_path / "house.json"
    db.write_text(
        json.dumps({"location": {"latitude": 10.0, "longitude": 20.0}, "globalVariables": {}})
    )
    engine = LuaEngine(db_path=str(db), db_persist=True)
    assert engine.api.state.location["latitude"] == 10.0
    engine.mark_db_dirty()
    engine._flush_db()
    saved = json.loads(db.read_text(encoding="utf-8"))
    assert saved["location"]["longitude"] == 20.0


def test_flua_lua_configures_location(tmp_path, monkeypatch) -> None:
    # .flua.lua can set the sim's location (device 1's sun times)
    (tmp_path / ".flua.lua").write_text(
        "return { location = { latitude = -33.87, longitude = 151.21 } }\n"  # Sydney
    )
    monkeypatch.chdir(tmp_path)
    engine = LuaEngine()
    assert engine.api.state.location["latitude"] == -33.87
    assert engine.api.state.location["longitude"] == 151.21
    # Sun times render in the host's timezone (like flua's os.date), so
    # only the shape is asserted here.
    sun = engine.api.state.sun_times(datetime(2026, 6, 21, 12, 0).timestamp())
    assert HH_MM.match(sun["sunriseHour"]) and HH_MM.match(sun["sunsetHour"])


def test_location_directive_wins_over_config(tmp_path, monkeypatch) -> None:
    # precedence: db/seed < .flua.lua < --%%location < runtime PUT
    (tmp_path / ".flua.lua").write_text(
        "return { location = { latitude = 1.0, longitude = 2.0 } }\n"
    )
    monkeypatch.chdir(tmp_path)
    engine = LuaEngine(location={"latitude": 59.33, "longitude": 18.07})
    assert engine.api.state.location == {"latitude": 59.33, "longitude": 18.07}
    # a runtime PUT wins over the directive
    engine.api.dispatch("PUT", "/settings/location", {"latitude": 9.0, "longitude": 9.0})
    assert engine.api.state.location["latitude"] == 9.0


@pytest.mark.asyncio
async def test_fibaro_get_value_sunset(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "function QuickApp:onInit()\n"
        "  print('SUNSET', tostring(fibaro.getValue(1, 'sunsetHour')))\n"
        "  print('NAME', tostring(fibaro.getName(1)))\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    match = re.search(r"SUNSET (\d{2}:\d{2})", out)
    assert match, out
    assert "NAME HC3" in out


@pytest.mark.asyncio
async def test_online_sun_times_follow_the_virtual_clock(
    tmp_path, capsys, mini_hc3, monkeypatch
) -> None:
    # online: the sim's device 1 answers first, so sun times follow the
    # virtual clock even when the (mock) HC3 serves different values
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mini_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    a = tmp_path / "a.lua"
    a.write_text(
        "function QuickApp:onInit()\n"
        "  local dev = api.get('/devices/1')\n"
        "  print('SUN', dev.properties.sunsetHour)\n"
        "end\n"
    )
    engine = LuaEngine(api_mode="remote")
    await engine.start()
    try:
        engine.start_qa(str(a), None, {}, str(a))
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    # the mock HC3 claims 99:99 for its device 1; the sim must not echo it
    assert re.search(r"SUN \d{2}:\d{2}", out)
    assert "99:99" not in out
