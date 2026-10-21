"""Devices category: list/query, CRUD, properties subpath (hc3-rest-api devices.md)."""

from __future__ import annotations

import time
import urllib.parse
from typing import Any

from ... import messages
from ...devices import skeleton_for
from ..request import ApiRequest, forward_to_proxy
from ..state import SimState, public


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes")


def _stringify(value: Any) -> str | None:
    """The HC3's property-filter stringification: Lua-style tostring."""
    if value is None:
        return None
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _matches(dev: dict[str, Any], query: dict[str, str]) -> bool:
    if "type" in query and dev.get("type") != query["type"]:
        return False
    if "name" in query and str(dev.get("name") or "").lower() != query["name"].lower():
        # the HC3 matches case-insensitively (observed: "Wake on LAN" hit "Wake on Lan")
        return False
    if "property" in query:
        # ?property=[name,value] — the HC3 stringifies the property value and
        # compares it to the filter value as a string (e.g. [value,false])
        prop = query["property"].strip()
        if not (prop.startswith("[") and prop.endswith("]")):
            return False
        name, _, value = prop[1:-1].partition(",")
        got = _stringify((dev.get("properties") or {}).get(name.strip()))
        if got is None or got != value.strip():
            return False
    if "parentId" in query and str(dev.get("parentId", 0)) != query["parentId"]:
        return False
    if "interface" in query and query["interface"] not in (dev.get("interfaces") or []):
        return False
    for key in ("visible", "enabled"):
        if key in query and _truthy(dev.get(key, True)) is not _truthy(query[key]):
            return False
    if "roomID" in query and str(dev.get("roomID", 0)) != query["roomID"]:
        return False
    return True


def _device1_merged(state: SimState, req: ApiRequest) -> dict | None:
    """Online: device 1 IS the controller — the real HC3's struct with the
    virtual-clock sun times on top (fetched lazily, cached for the run)."""
    if req.remote_cached is None or req.clock is None:
        return None
    cached = req.remote_cached("/devices/1")
    if cached is None or not isinstance(cached[0], dict):
        return None
    out = dict(cached[0])
    props = dict(out.get("properties") or {})
    props.update(state.sun_times(req.clock.time))
    out["properties"] = props
    return out


def _with_sun(dev: dict, state: SimState, clock: Any) -> dict:
    """Device 1 is the HC3 itself: its sunrise/sunset follow the virtual
    clock's date, computed on read (also in online mode — the sim answers
    first, so the virtual clock wins over the real HC3's values)."""
    if clock is None or int(dev.get("id") or 0) != 1:
        return dev
    out = dict(dev)
    props = dict(out.get("properties") or {})
    props.update(state.sun_times(clock.time))
    out["properties"] = props
    return out


def devices_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    name_query = req.query.get("name")
    if name_query is not None and "&" in name_query and req.emit is not None:
        # the HC3 cannot match names containing '&' at all (its filter
        # re-splits on the decoded ampersand and returns 0 — verified live).
        # flua matches correctly, so a QA that works here returns nothing on
        # the controller: warn, don't silently diverge.
        req.emit(
            messages.log(
                "warning",
                "flua: ?name= filter contains '&' — the HC3 returns 0 matches "
                "for such names; this QA will behave differently on the controller",
            )
        )
    devices = [d for d in state.devices.values() if _matches(d, req.query)]
    if req.remote is not None:
        # online: the developer should feel at home on the HC3 — serve the
        # union of the emulated devices and the controller's (the same query
        # is forwarded). Emulated devices win on id clashes, so a proxy QA
        # and its HC3 twin (same deviceID) count once — except device 1,
        # the controller itself: its struct comes from the HC3 with the
        # virtual-clock sun times on top.
        query_string = urllib.parse.urlencode(req.query)
        path = "/devices" + (f"?{query_string}" if query_string else "")
        remote_devices, status = req.remote("GET", path, None)
        if status == 200 and isinstance(remote_devices, list):
            merged = {int(device["id"]): device for device in remote_devices}
            merged.update({int(device["id"]): device for device in devices})
            if 1 in merged and 1 in state.devices:
                one = _device1_merged(state, req)
                if one is not None:
                    merged[1] = one
            devices = list(merged.values())
    devices = [_with_sun(d, state, req.clock) for d in devices]
    return public(sorted(devices, key=lambda d: d["id"])), 200


def flua_theme(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """GET /flua/theme — the viewer's default colors from .flua.lua
    (viewer = { bg = ..., panel = ... }); {} when not configured."""
    return dict(getattr(state, "viewer_theme", {}) or {}), 200


def flua_devices_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """GET /flua/devices — the UI viewer's device list (flua-only channel).

    The emulated devices only: the HC3's own QAs stay out (a controller can
    carry a hundred of them; the viewer renders the QAs you run in flua).
    No online union — the remote hook is deliberately unused.
    """
    devices = [_with_sun(d, state, req.clock) for d in state.devices.values()]
    return public(sorted(devices, key=lambda d: d["id"])), 200


def device_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.device(req.path_params["id"])
    if dev is not None:
        if int(dev["id"]) == 1:
            # device 1 is the controller: online, its struct comes from the
            # HC3 with the virtual-clock sun times on top
            merged = _device1_merged(state, req)
            if merged is not None:
                return public(merged), 200
        return public(_with_sun(dev, state, req.clock)), 200
    return None, 404


def device_update(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.device(req.path_params["id"])
    if dev is None:
        return None, 404
    if not isinstance(req.body, dict):
        return None, 400
    # the HC3 only lets a handful of top-level fields be updated: the four
    # restarting scalars plus a MERGED properties dict (changed keys restart
    # too — only /plugins/updateProperty is the non-restarting channel)
    disallowed = sorted(
        k for k in req.body if k not in ("name", "enabled", "visible", "roomID", "properties")
    )
    if disallowed:
        return {"error": f"cannot update field(s): {', '.join(disallowed)}"}, 400
    proxy = state.is_proxy(dev["id"])
    restart = False
    for key in ("name", "enabled", "visible", "roomID"):
        if key in req.body:
            old = dev.get(key)
            dev[key] = req.body[key]
            if not proxy:
                state.record_change(dev["id"], key, req.body[key], old)
            if req.body[key] != old:
                restart = True
    if "properties" in req.body:
        incoming = req.body["properties"]
        if not isinstance(incoming, dict):
            return None, 400
        properties = dev.setdefault("properties", {})
        for name, value in incoming.items():
            old = properties.get(name)
            properties[name] = value  # merge: other properties stay untouched
            if proxy:
                continue  # the HC3 owns the device; its events come back via the poll
            entry = state.record_property_event(dev["id"], name, value, old, _now(req))
            if entry is not None:
                restart = True  # a real change through the device route restarts
                if req.emit is not None:
                    req.emit(messages.refresh_state_event(entry))
        dev["modified"] = int(_now(req))
    if proxy:
        # the HC3 owns the device: mirror the update there; it restarts its
        # own plugin, and the change feed comes back through the poll
        forward_to_proxy(req, True)
    elif restart and dev.get("isPlugin") and req.restart_qa is not None:
        req.restart_qa(int(dev["id"]))
    return None, 204


def device_create(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # POST /devices — the HC3 creates plugin devices here; flua extends the
    # route to create BASE devices (no QA): name + type are required, the
    # rest of the fields come from the type skeleton, and a properties dict
    # merges over the skeleton defaults. The device behaves like a
    # db-seeded one (layer-1 default actions).
    if not isinstance(req.body, dict):
        return None, 400
    name = req.body.get("name")
    device_type = req.body.get("type")
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(device_type, str)
        or not device_type
    ):
        return None, 400
    properties = req.body.get("properties")
    if properties is not None and not isinstance(properties, dict):
        return None, 400
    room_id = req.body.get("roomID")
    if room_id is not None:
        try:
            room_id = int(room_id)
        except (TypeError, ValueError):
            return None, 400
    try:
        device, event = state.add_base_device(name, device_type, properties, room_id, _now(req))
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if event is not None and req.emit is not None:
        req.emit(messages.refresh_state_event(event))
    return public(device), 200


def device_delete(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.device(req.path_params["id"])
    if dev is None:
        return None, 404
    device_id = int(req.path_params["id"])
    del state.devices[device_id]
    if state.is_proxy(device_id):
        # the HC3 owns the device; its own events come back via the poll
        return None, 204
    entry = state.record_device_removed(dev, _now(req))
    if req.emit is not None:
        req.emit(messages.refresh_state_event(entry))
    return None, 204


def device_property_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.device(req.path_params["id"])
    if dev is None:
        return None, 404
    name = req.path_params["name"]
    if int(dev.get("id") or 0) == 1 and req.clock is not None and name in (
        "sunriseHour",
        "sunsetHour",
    ):
        # the HC3's own device: computed for the virtual clock's date
        return public(state.sun_times(req.clock.time)[name]), 200
    value = (dev.get("properties") or {}).get(name)
    if value is None:
        return None, 404
    return public(value), 200


def device_property_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # PUT /devices/{id}/properties/{name} — the device-route properties
    # update. Unlike /plugins/updateProperty (the HC3's non-restarting
    # channel) a change here restarts the QA, like every other top-level
    # device PUT.
    dev = state.device(req.path_params["id"])
    if dev is None:
        return None, 404
    name = req.path_params["name"]
    if not isinstance(req.body, dict) or "value" not in req.body:
        return None, 400
    properties = dev.setdefault("properties", {})
    old = properties.get(name)
    value = req.body["value"]
    properties[name] = value
    dev["modified"] = int(_now(req))
    if state.is_proxy(dev["id"]):
        forward_to_proxy(req, True)
        return None, 204
    entry = state.record_property_event(dev["id"], name, value, old, _now(req))
    if entry is not None and req.emit is not None:
        req.emit(messages.refresh_state_event(entry))
    if entry is not None and dev.get("isPlugin") and req.restart_qa is not None:
        req.restart_qa(int(dev["id"]))
    return None, 204


def _default_action_value(action: str, device_type: Any, args: list[Any]) -> Any:
    """The canonical light-action semantics for seeded (non-plugin)
    devices: binary switches flip value, dimmers use 0/99 levels — the same
    values the quickapp-types templates use."""
    dimmer = str(device_type or "").endswith("multilevelSwitch")
    if action == "turnOn":
        return 99 if dimmer else True
    if action == "turnOff":
        return 0 if dimmer else False
    if action == "setValue" and args:
        raw = args[0]
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            lowered = raw.lower()
            if lowered == "on":
                return 99 if dimmer else True
            if lowered == "off":
                return 0 if dimmer else False
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def _apply_default_action(
    state: SimState, req: ApiRequest, dev: dict[str, Any], args: list[Any]
) -> None:
    """Layer 1 device emulation: seeded physical devices (no QA behind
    them) react to the canonical light actions by updating their value —
    the house behaves without starting any QA. QAs/plugins and proxy
    devices never reach here (their actions run real code / the HC3)."""
    if dev.get("isPlugin") or state.is_proxy(dev["id"]):
        return
    new_value = _default_action_value(req.path_params["action"], dev.get("type"), args)
    if new_value is None:
        return
    # the catalog's interfaces are the gate: light-like devices switch
    # value, sensors and meters stay inert
    skeleton = skeleton_for(dev.get("type"))
    interfaces = dev.get("interfaces") or (skeleton or {}).get("interfaces") or []
    if "light" not in interfaces:
        return
    properties = dev.setdefault("properties", {})
    old = properties.get("value")
    properties["value"] = new_value
    dev["modified"] = int(_now(req))
    entry = state.record_property_event(dev["id"], "value", new_value, old, _now(req))
    if entry is not None and req.emit is not None:
        req.emit(messages.refresh_state_event(entry))


def action_device(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """POST /devices/{id}/action/{action}: accepted here, run via the pump."""
    dev = state.device(req.path_params["id"])
    if dev is None:
        return None, 404
    args = req.body.get("args") if isinstance(req.body, dict) else None
    if args is None:
        args = []
    if not isinstance(args, (list, tuple)):
        return None, 400
    if req.emit is not None:
        req.emit(messages.device_action(int(dev["id"]), req.path_params["action"], list(args)))
    # Actions arriving from a proxy callback were already recorded by the
    # real HC3 (DeviceActionRanEvent) — the poll mirrors that event, so the
    # sim must not emit a duplicate.
    if req.external and state.is_proxy(dev["id"]):
        return None, 202
    entry = state.record_action_event(
        int(dev["id"]), req.path_params["action"], list(args), _now(req)
    )
    if entry is not None and req.emit is not None:
        req.emit(messages.refresh_state_event(entry))
    _apply_default_action(state, req, dev, list(args))
    return None, 202


def group_action(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """POST /devices/groupAction/{action}: fan out one action per device."""
    if not isinstance(req.body, dict) or not isinstance(req.body.get("devices"), (list, tuple)):
        return None, 400
    args = req.body.get("args") or []
    if not isinstance(args, (list, tuple)):
        return None, 400
    acted: list[int] = []
    for device_id in req.body["devices"]:
        if state.device(device_id) is None:
            continue  # like the HC3: unknown ids are skipped
        acted.append(int(device_id))
        if req.emit is not None:
            req.emit(messages.device_action(int(device_id), req.path_params["action"], list(args)))
        entry = state.record_action_event(
            int(device_id), req.path_params["action"], list(args), _now(req)
        )
        if entry is not None and req.emit is not None:
            req.emit(messages.refresh_state_event(entry))
    return {"devices": acted}, 202


def _now(req: ApiRequest) -> float:
    return req.clock.time if req.clock is not None else time.time()
