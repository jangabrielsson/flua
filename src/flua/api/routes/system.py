"""System category: global variables and rooms (hc3-rest-api system.md)."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from ... import messages
from ..request import ApiRequest
from ..state import SimState, public


def _now(req: ApiRequest) -> float:
    return req.clock.time if req.clock is not None else time.time()


def location_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # GET /settings/location — the controller's location (drives device 1's
    # sunrise/sunset)
    return public(state.location), 200


def location_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # PUT /settings/location — the HC3 accepts the full settings object;
    # the sim keeps latitude/longitude (the fields suncalc uses)
    if not isinstance(req.body, dict):
        return None, 400
    for key in ("latitude", "longitude"):
        if key in req.body:
            state.location[key] = req.body[key]
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
    sun = state.sun_times(_now(req))
    offset = datetime.now().astimezone().utcoffset()
    timezone_offset = int(offset.total_seconds() // 60) if offset else 0
    return public(
        {
            "serialNumber": "HC3-00000000",
            "softVersion": "flua",
            "hcName": (state.devices.get(1) or {}).get("name", "HC3"),
            "defaultRoomId": 219,
            "timezoneOffset": timezone_offset,
            "sunriseHour": sun["sunriseHour"],
            "sunsetHour": sun["sunsetHour"],
        }
    ), 200


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
    return public(
        {
            "hcName": (state.devices.get(1) or {}).get("name", "HC3"),
            "timestamp": int(_now(req)),
            "defaultSensors": {"temperature": True, "light": True},
        }
    ), 200


def debug_messages_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    return public({"messages": [], "nextLast": 0}), 200


def weather_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # no weather provider in the sim: zeroed values, HC3-shaped
    return public(
        {
            "ConditionCode": 0,
            "Humidity": None,
            "Temperature": None,
            "TemperatureUnit": "C",
            "WeatherCondition": "",
            "WeatherConditionConverted": "",
            "Wind": None,
            "WindUnit": "m/s",
        }
    ), 200


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
    return public([]), 200


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
