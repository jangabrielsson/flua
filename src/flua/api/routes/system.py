"""System category: global variables and rooms (hc3-rest-api system.md)."""

from __future__ import annotations

import time
from typing import Any

from ... import messages
from ..request import ApiRequest
from ..state import SimState, public


def _now(req: ApiRequest) -> float:
    return req.clock.time if req.clock is not None else time.time()


def _date_time_parts(now: float) -> tuple[dict[str, int], dict[str, int]]:
    """The HC3's date/time settings fields, from the virtual clock's local
    date (so online runs report virtual time, like device 1's sun times)."""
    local = time.localtime(now)
    return (
        {"day": local.tm_mday, "month": local.tm_mon, "year": local.tm_year},
        {"hour": local.tm_hour, "minute": local.tm_min},
    )


def location_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # GET /settings/location — the controller's location (drives device 1's
    # sunrise/sunset); date/time follow the virtual clock
    out = dict(state.location)
    date, clock = _date_time_parts(_now(req))
    out["date"] = date
    out["time"] = clock
    return public(out), 200


def location_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # PUT /settings/location — the HC3 accepts the full settings object;
    # the sim merges every scalar field (latitude/longitude drive suncalc)
    if not isinstance(req.body, dict):
        return None, 400
    for key, value in req.body.items():
        # date/time are computed fields (virtual clock); everything scalar merges
        if key not in ("date", "time") and not isinstance(value, (dict, list)):
            state.location[key] = value
    return None, 200


def globals_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    variables = sorted(state.global_variables.values(), key=lambda v: v["name"])
    return public(variables), 200


def global_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    var = state.global_variables.get(req.path_params["name"])
    return (public(var), 200) if var is not None else (None, 404)


def global_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    if not isinstance(req.body, dict) or "value" not in req.body:
        return None, 400
    name = req.path_params["name"]
    existing = state.global_variables.get(name)
    if existing is None:
        # the real HC3 404s a PUT on a missing variable — create goes
        # through POST /globalVariables
        return None, 404
    value = "" if req.body["value"] is None else str(req.body["value"])
    old_value = existing.get("value")
    var = {
        "name": name,
        "value": value,
        # modified is the sim's current time (os.time() in QA code), like the
        # HC3 stamps writes with the controller clock
        "modified": int(_now(req)),
    }
    state.global_variables[name] = var
    entry = state.record_global_changed(name, value, old_value, _now(req))
    if entry is not None and req.emit is not None:
        req.emit(messages.refresh_state_event(entry))
    return public(var), 200


def globals_create(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # POST /globalVariables — the real HC3's create-a-global-variable call
    if not isinstance(req.body, dict) or not req.body.get("name"):
        return None, 400
    name = str(req.body["name"])
    if name in state.global_variables:
        # creating over an existing variable is a conflict — the value stays
        return None, 409
    value = req.body.get("value")
    var = {
        "name": name,
        "value": "" if value is None else str(value),
        "modified": int(_now(req)),
    }
    state.global_variables[name] = var
    entry = state.record_global_added(name, var["value"], _now(req))
    if req.emit is not None:
        req.emit(messages.refresh_state_event(entry))
    return public(var), 200


def global_delete(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # DELETE /globalVariables/{name} — fibaro.deleteGlobalVariable
    name = req.path_params["name"]
    var = state.global_variables.pop(name, None)
    if var is None:
        return None, 404
    entry = state.record_global_removed(name, _now(req))
    if req.emit is not None:
        req.emit(messages.refresh_state_event(entry))
    return None, 204


def rooms_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    rooms = sorted(state.rooms.values(), key=lambda r: r["id"])
    return public(rooms), 200


def room_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    try:
        room = state.rooms.get(int(req.path_params["id"]))
    except (TypeError, ValueError):
        room = None
    return (public(room), 200) if room is not None else (None, 404)


def settings_info(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # GET /settings/info — the controller's identity + the day's sun times
    # (all virtual-clock-derived: online runs report the simulated time);
    # PUT overrides merge on top
    now = _now(req)
    sun = state.sun_times(now)
    name = (state.devices.get(1) or {}).get("name", "HC3")
    info = {
        "serialNumber": "HC3-00000000",
        "platform": "HC3",
        "zwaveEngineVersion": "2.0",
        "zigbeeStatus": True,
        "hcName": name,
        "mac": "ac:17:a2:0d:35:e8",
        "zwaveVersion": "4.33",
        "timeFormat": 24,
        "zwaveRegion": "EU",
        "serverStatus": int(now),
        "defaultLanguage": "en",
        "defaultRoomId": 219,
        "sunsetHour": sun["sunsetHour"],
        "sunriseHour": sun["sunriseHour"],
        "hotelMode": False,
        "temperatureUnit": "C",
        "batteryLowNotification": False,
        "date": time.strftime("%H:%M | %d.%m.%Y", time.localtime(now)),
        "dateFormat": "dd.mm.yy",
        "decimalMark": ".",
        "timezoneOffset": state.location.get("timezoneOffset", 7200),
        "currency": "EUR",
        "softVersion": "flua",  # the honest identity: flua is not a firmware
        "beta": False,
        "currentVersion": {"version": "flua", "type": "stable"},
        "installVersion": {"version": "", "type": "", "status": "", "progress": 0},
        "timestamp": int(now),
        "online": False,
        "tosAccepted": True,
        "skin": "light",
        "skinSetting": "manual",
        "updateStableAvailable": False,
        "updateBetaAvailable": False,
        "newestStableVersion": "flua",
        "newestBetaVersion": "5.0.0",
        "isFTIConfigured": True,
        "isSlave": False,
        "hasFIDConnected": True,
        "oemId": "HC3",
    }
    info.update(state.info_overrides)
    return public(info), 200


_INFO_COMPUTED = ("sunriseHour", "sunsetHour", "date", "timestamp", "serverStatus")


def settings_info_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # PUT /settings/info — the HC3 accepts the full settings object; the
    # sim merges scalar fields (computed virtual-clock fields stay computed)
    if not isinstance(req.body, dict):
        return None, 400
    for key, value in req.body.items():
        if key in _INFO_COMPUTED or isinstance(value, (dict, list)):
            continue
        state.info_overrides[key] = value
    # hcName IS device 1's name on the HC3 — keep them in sync
    if "hcName" in req.body and 1 in state.devices:
        state.devices[1]["name"] = req.body["hcName"]
    return None, 200


def sections_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    sections = sorted(state.sections.values(), key=lambda s: s["id"])
    return public(sections), 200


def section_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    try:
        section = state.sections.get(int(req.path_params["id"]))
    except (TypeError, ValueError):
        section = None
    return (public(section), 200) if section is not None else (None, 404)


def custom_events_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public(list(state.custom_events)), 200


def custom_event_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    name = req.path_params["name"]
    for event in state.custom_events:
        if event.get("name") == name:
            return public(event), 200
    return None, 404


def ios_devices_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public([]), 200  # the sim has no iOS companions


def home_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    home = {
        "timestamp": int(_now(req)),
        "defaultSensors": {"temperature": 0, "humidity": 0, "light": 0},
        "notificationClient": {"marketingNotificationAllowed": True},
        "hcName": (state.devices.get(1) or {}).get("name", "HC3"),
        "weatherProvider": 3,
        "currency": "EUR",
        "fireAlarmTemperature": 60,
        "freezeAlarmTemperature": 1,
        "timeFormat": 24,
        "dateFormat": "dd.mm.yy",
        "firstRunAfterUpdate": False,
    }
    home.update(state.home_overrides)
    return public(home), 200


def home_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # PUT /home — the HC3 accepts the full settings object; scalars merge,
    # the two known object fields replace wholesale, timestamp stays virtual
    if not isinstance(req.body, dict):
        return None, 400
    for key, value in req.body.items():
        if key == "timestamp":
            continue
        if key in ("defaultSensors", "notificationClient") or not isinstance(
            value, (dict, list)
        ):
            state.home_overrides[key] = value
    return None, 200


def _int_param(query: dict[str, str], name: str) -> int | None:
    """Parse an optional integer query param; raises ValueError on bad
    values (callers turn that into a 400)."""
    raw = query.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValueError(name) from None


def debug_messages_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """GET /debugMessages — the QA console buffer, in the real HC3's
    DebugMessagesDto shape. Query params match the HC3's debugMessages API:
    ``last`` (only messages with id > last), ``offset`` (return the newest N;
    -1 = all), ``filter`` (comma list of tags), ``types`` (comma list of
    message types), ``from``/``to`` (timestamp bounds)."""
    query = req.query
    try:
        last = _int_param(query, "last") or 0
        offset_raw = _int_param(query, "offset")
        from_ts = _int_param(query, "from")
        to_ts = _int_param(query, "to")
    except ValueError:
        return None, 400
    offset = -1 if offset_raw is None else offset_raw
    tags = [t for t in (query.get("filter") or "").split(",") if t]
    types = [t for t in (query.get("types") or "").split(",") if t]
    messages = [m for m in state.debug_messages if m["id"] > last]
    if tags:
        messages = [m for m in messages if m.get("tag") in tags]
    if types:
        messages = [m for m in messages if m["type"] in types]
    if from_ts is not None:
        messages = [m for m in messages if m["timestamp"] >= from_ts]
    if to_ts is not None:
        messages = [m for m in messages if m["timestamp"] <= to_ts]
    if offset >= 0:
        messages = [] if offset == 0 else messages[-offset:]
    next_last = messages[-1]["id"] if messages else 0
    return public({"nextLast": next_last, "messages": messages}), 200


def debug_messages_delete(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """DELETE /debugMessages — clear the console buffer."""
    state.clear_debug_messages()
    return None, 204


def debug_messages_tags(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """GET /debugMessages/tags — the distinct QA tags seen so far."""
    tags = sorted({m["tag"] for m in state.debug_messages if m.get("tag")})
    return public(tags), 200


def flua_system_log(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """GET /flua/systemLog — flua's structured lifecycle/crash feed (the
    machine-readable system log the real HC3 lacks). Same polling pattern
    as /debugMessages: ``last`` (only entries with id > last), ``offset``
    (the newest N; -1 = all). Entries: {id, time, event, qa, tag, code,
    detail} — events: run_start/run_stop, qa_load/qa_restart/qa_exit,
    qa_error, crash, error."""
    query = req.query
    try:
        last = _int_param(query, "last") or 0
        offset_raw = _int_param(query, "offset")
    except ValueError:
        return None, 400
    offset = -1 if offset_raw is None else offset_raw
    entries = [e for e in state.system_events if e["id"] > last]
    if offset >= 0:
        entries = [] if offset == 0 else entries[-offset:]
    next_last = entries[-1]["id"] if entries else 0
    return public({"nextLast": next_last, "entries": entries}), 200


def flua_system_log_delete(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """DELETE /flua/systemLog — clear the lifecycle buffer."""
    state.clear_system_events()
    return None, 204


def weather_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # no weather provider in the sim: stable fake data, HC3-shaped, units
    # from the configured location; PUT /weather overrides any field (a
    # flua extension — the HC3's weather is provider-owned)
    weather = {
        "ConditionCode": 1,
        "Humidity": 62.0,
        "Temperature": 12.5,
        "TemperatureUnit": state.location.get("temperatureUnit", "C"),
        "WeatherCondition": "Partly cloudy",
        "WeatherConditionConverted": "Partly cloudy",
        "Wind": 4.2,
        "WindUnit": state.location.get("windUnit", "km/h"),
    }
    weather.update(state.weather_overrides)
    return public(weather), 200


def weather_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # PUT /weather — flua-only (no HC3 counterpart): a test QA sets the
    # weather its scene logic reacts to
    if not isinstance(req.body, dict):
        return None, 400
    for key, value in req.body.items():
        if not isinstance(value, (dict, list)):
            state.weather_overrides[key] = value
    return None, 200


def alarm_devices_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public([]), 200  # no devices are armed into the alarm


def notification_center_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public([]), 200


def profile_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    try:
        profile = state.profiles.get(int(req.path_params["id"]))
    except (TypeError, ValueError):
        profile = None
    if profile is None:
        return None, 404
    out = dict(profile)
    for key in ("climateZones", "devices", "partitions", "scenes"):
        out.setdefault(key, [])
    return public(out), 200


def icons_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return None, 200  # the HC3 response carries no body (per the reference)


def users_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # the controller always has at least the admin user
    return public([{"id": 1, "name": "admin", "type": "superuser"}]), 200


def energy_devices_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public([]), 200


def panels_location(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # the location panels; the home panel's lat/long always follow the
    # configured location (like device 1's sun times follow the clock)
    latitude = state.location.get("latitude")
    longitude = state.location.get("longitude")
    panels = []
    for panel in state.family_locations:
        out = dict(panel)
        if panel.get("home"):
            out["latitude"] = latitude
            out["longitude"] = longitude
        panels.append(out)
    return public(panels), 200


def panel_location_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # PUT /panels/location/{id} — update a location panel (name/radius/
    # address/home); lat/long stay driven by the configured location
    if not isinstance(req.body, dict):
        return None, 400
    try:
        panel_id = int(req.path_params["id"])
    except (KeyError, TypeError, ValueError):
        return None, 404
    for panel in state.family_locations:
        if panel.get("id") == panel_id:
            for key in ("name", "radius", "address", "home"):
                if key in req.body:
                    panel[key] = req.body[key]
            return None, 200
    return None, 404


def panels_climate(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    zones = sorted(state.climate_zones.values(), key=lambda z: z["id"])
    return public(zones), 200


def panel_climate_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    try:
        zone = state.climate_zones.get(int(req.path_params["id"]))
    except (TypeError, ValueError):
        zone = None
    return (public(zone), 200) if zone is not None else (None, 404)


def panels_notifications(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public({"notifications": []}), 200


def panels_family(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public([]), 200


def panels_sprinklers(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public([]), 200


def panels_humidity(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public([]), 200


def panels_favorite_colors(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public([]), 200


def diagnostics_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public({"cpuLoad": 0, "memory": 0, "storage": 0}), 200


def proxy_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # GET /proxy?url=... — the HC3's UI helper fetches a URL server-side
    url = req.query.get("url")
    if not url:
        return None, 400
    if req.fetch is None:
        return None, 501
    status, body, _headers = req.fetch(url)
    if status is None:
        return None, 502
    return body, status


def refresh_states(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """GET /refreshStates?last=N — the HC3's polling contract.

    The base fields (status/last/date/timestamp/timestampMillis) are always
    present, like the real HC3's idle response; changes/events appear only
    when something has been emitted since ``last`` (they vary with activity
    on the real HC3 too).
    """
    try:
        last = int(req.query.get("last", 0) or 0)
    except ValueError:
        return None, 400
    epoch = time.time() if req.clock is None else req.clock.time
    response: dict[str, Any] = {
        "status": "IDLE",
        "last": state.refresh_seq(),
        "date": time.strftime("%H:%M | %d.%m.%Y", time.localtime(epoch)),
        "timestamp": int(epoch),
        "timestampMillis": int(epoch * 1000),
    }
    changes = [entry for seq, entry in state.changes if seq > last]
    events = [entry for seq, entry in state.events if seq > last]
    if changes:
        response["changes"] = changes
    if events:
        response["events"] = events
    return response, 200


def profiles_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    profiles = sorted(state.profiles.values(), key=lambda p: p["id"])
    return public(profiles), 200


def profile_activate(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    try:
        profile_id = int(req.path_params["id"])
    except ValueError:
        return None, 404
    if profile_id not in state.profiles:
        return None, 404
    for profile in state.profiles.values():
        profile["active"] = profile["id"] == profile_id
    return None, 202
