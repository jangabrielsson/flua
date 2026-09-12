"""System category: global variables and rooms (hc3-rest-api system.md)."""

from __future__ import annotations

from typing import Any

from ..request import ApiRequest
from ..state import SimState, public


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
    value = req.body["value"]
    var = {
        "name": name,
        "value": "" if value is None else str(value),
        "modified": int(req.body.get("modified", 0) or 0),
    }
    state.global_variables[name] = var
    return public(var), 200


def rooms_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    rooms = sorted(state.rooms.values(), key=lambda r: r["id"])
    return public(rooms), 200


def room_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    try:
        room = state.rooms.get(int(req.path_params["id"]))
    except (TypeError, ValueError):
        room = None
    return (public(room), 200) if room is not None else (None, 404)


def refresh_states(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """GET /refreshStates?last=N: changes and events with seq > N."""
    try:
        last = int(req.query.get("last", 0) or 0)
    except ValueError:
        return None, 400
    return {
        "last": state.refresh_seq(),
        "changes": [entry for seq, entry in state.changes if seq > last],
        "events": [entry for seq, entry in state.events if seq > last],
    }, 200


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