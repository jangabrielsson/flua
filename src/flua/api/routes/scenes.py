"""Scenes and custom events (hc3-rest-api scenes-automation.md).

Scenes are metadata + run state in the offline sim (no scene Lua code yet);
custom events are recorded in the refreshStates feed and delivered to QAs
that define an ``onCustomEvent`` method (a flua extension — on the real
HC3 they trigger scenes).
"""

from __future__ import annotations

from typing import Any

from ... import messages
from ..request import ApiRequest
from ..state import SimState, public


def scenes_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    scenes = sorted(state.scenes.values(), key=lambda s: s["id"])
    return public(scenes), 200


def scene_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    scene = state.scene(req.path_params["id"])
    return (public(scene), 200) if scene is not None else (None, 404)


def scene_execute(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    scene = state.scene(req.path_params["id"])
    if scene is None:
        return None, 404
    scene["running"] = True
    return None, 202


def scene_kill(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    scene = state.scene(req.path_params["id"])
    if scene is None:
        return None, 404
    scene["running"] = False
    return None, 202


def custom_event_post(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    name = req.path_params["name"]
    state.record_event(name)
    if req.emit is not None:
        req.emit(messages.custom_event(name))
    return None, 202


def custom_event_post_body(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # POST /customEvents with a body ({name=..., userDescription=...}) — the
    # CustomEventDto form the HC3 accepts
    if not isinstance(req.body, dict) or not req.body.get("name"):
        return None, 400
    entry = {"name": str(req.body["name"])}
    if req.body.get("userDescription") is not None:
        entry["userDescription"] = req.body["userDescription"]
    state.custom_events.append(entry)
    if req.emit is not None:
        req.emit(messages.custom_event(entry["name"]))
    return public(entry), 201
