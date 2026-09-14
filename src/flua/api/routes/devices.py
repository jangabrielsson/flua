"""Devices category: list/query, CRUD, properties subpath (hc3-rest-api devices.md)."""

from __future__ import annotations

import time
from typing import Any

from ... import messages
from ..request import ApiRequest
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


def devices_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    devices = [d for d in state.devices.values() if _matches(d, req.query)]
    return public(sorted(devices, key=lambda d: d["id"])), 200


def device_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.device(req.path_params["id"])
    return (public(dev), 200) if dev is not None else (None, 404)


def device_update(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.device(req.path_params["id"])
    if dev is None:
        return None, 404
    if not isinstance(req.body, dict):
        return None, 400
    for key in ("name", "enabled", "visible", "roomID"):
        if key in req.body:
            old = dev.get(key)
            dev[key] = req.body[key]
            state.record_change(dev["id"], key, req.body[key], old)
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
    value = (dev.get("properties") or {}).get(req.path_params["name"])
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
