"""Devices category: list/query, CRUD, properties subpath (hc3-rest-api devices.md)."""

from __future__ import annotations

import time
import urllib.parse
from typing import Any

from ... import messages
from ..request import ApiRequest, forward_to_proxy
from ..state import SimState, public


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes")


def _matches(dev: dict[str, Any], query: dict[str, str]) -> bool:
    if "type" in query and dev.get("type") != query["type"]:
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
    devices = [d for d in state.devices.values() if _matches(d, req.query)]
    if req.remote is not None:
        # online: the developer should feel at home on the HC3 — serve the
        # union of the emulated devices and the controller's (the same query
        # is forwarded). Emulated devices win on id clashes, so a proxy QA
        # and its HC3 twin (same deviceID) count once — and the sim's device
        # 1 (the HC3 itself) wins over the controller's, keeping sun times
        # on the virtual clock.
        query_string = urllib.parse.urlencode(req.query)
        path = "/devices" + (f"?{query_string}" if query_string else "")
        remote_devices, status = req.remote("GET", path, None)
        if status == 200 and isinstance(remote_devices, list):
            merged = {int(device["id"]): device for device in remote_devices}
            merged.update({int(device["id"]): device for device in devices})
            devices = list(merged.values())
    devices = [_with_sun(d, state, req.clock) for d in devices]
    return public(sorted(devices, key=lambda d: d["id"])), 200


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
    return (public(_with_sun(dev, state, req.clock)), 200) if dev is not None else (None, 404)


def device_update(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.device(req.path_params["id"])
    if dev is None:
        return None, 404
    if not isinstance(req.body, dict):
        return None, 400
    proxy = state.is_proxy(dev["id"])
    for key in ("name", "enabled", "visible", "roomID"):
        if key in req.body:
            old = dev.get(key)
            dev[key] = req.body[key]
            if not proxy:
                state.record_change(dev["id"], key, req.body[key], old)
    if proxy:
        # the HC3 owns the device: mirror the update there; its change feed
        # comes back through the refreshStates poll
        forward_to_proxy(req, True)
    return None, 204


def device_delete(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.device(req.path_params["id"])
    if dev is None:
        return None, 404
    del state.devices[int(req.path_params["id"])]
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
