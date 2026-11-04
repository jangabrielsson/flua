"""Scenes and custom events (hc3-rest-api scenes-automation.md).

Scenes are metadata + run state in the offline sim (no scene Lua code yet);
custom events are recorded in the refreshStates feed and delivered to QAs
that define an ``onCustomEvent`` method (a flua extension — on the real
HC3 they trigger scenes).
"""

from __future__ import annotations

from typing import Any

from ... import messages
from ..request import ApiRequest, remote_get
from ..state import SimState, public
from .plugins import VARIABLE_NAME_RE


def scenes_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # online: the controller's scenes plus the emu's local ones (scene QAs
    # register in the scene table); local scenes win on id clashes
    remote = remote_get(req, "/scenes")
    if remote is not None:
        remote_scenes, _ = remote
        if isinstance(remote_scenes, list):
            merged = {int(scene["id"]): scene for scene in remote_scenes}
            for scene in state.scenes.values():
                merged[int(scene["id"])] = scene
            return public(sorted(merged.values(), key=lambda s: s["id"])), 200
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
    if req.emit is not None:
        # a scene QA runs its actions (sourceTrigger = user); seeded
        # metadata-only scenes just flip their running state
        req.emit(messages.scene_execute(scene["id"]))
    return None, 202


def scene_kill(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    scene = state.scene(req.path_params["id"])
    if scene is None:
        return None, 404
    scene["running"] = False
    return None, 202


def _custom_event(state: SimState, name: str) -> dict[str, Any] | None:
    for entry in state.custom_events:
        if entry.get("name") == name:
            return entry
    return None


def custom_event_post(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # POST /customEvents/{name}: FIRE the event. Live HC3 (5.221): a
    # valid-but-unknown name still answers 204 — firing must not create,
    # but it also does not error. An INVALID name (the name-format rule) is
    # 501, the HC3's handler quirk for malformed names.
    name = req.path_params["name"]
    if VARIABLE_NAME_RE.fullmatch(name) is None:
        return None, 501
    if _custom_event(state, name) is not None:
        state.record_event(name)
        if req.emit is not None:
            req.emit(messages.custom_event(name))
    return None, 204


def custom_event_post_body(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # POST /customEvents with a body ({name=..., userDescription=...}) —
    # CREATES the CustomEventDto (201 + dto like the live HC3, 409 on a
    # duplicate name, 400 on an invalid name). Creation does not fire;
    # firing is POST /customEvents/{name}.
    if not isinstance(req.body, dict) or not req.body.get("name"):
        return None, 400
    name = str(req.body["name"])
    if VARIABLE_NAME_RE.fullmatch(name) is None:
        return None, 400
    if _custom_event(state, name) is not None:
        return None, 409
    entry = {"name": name}
    if req.body.get("userDescription") is not None:
        entry["userDescription"] = req.body["userDescription"]
    state.custom_events.append(entry)
    return public(entry), 201


def custom_event_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # PUT /customEvents/{name}: update name/userDescription (404 unknown,
    # 409 when the rename collides with another event, 501 invalid name)
    if not isinstance(req.body, dict):
        return None, 400
    name = req.path_params["name"]
    if VARIABLE_NAME_RE.fullmatch(name) is None:
        return None, 501
    entry = _custom_event(state, name)
    if entry is None:
        return None, 404
    new_name = str(req.body.get("name", name))
    if new_name != name and _custom_event(state, new_name) is not None:
        return None, 409
    entry["name"] = new_name
    if req.body.get("userDescription") is not None:
        entry["userDescription"] = req.body["userDescription"]
    return public(entry), 200


def custom_event_delete(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    name = req.path_params["name"]
    if VARIABLE_NAME_RE.fullmatch(name) is None:
        return None, 501
    for index, entry in enumerate(state.custom_events):
        if entry.get("name") == name:
            del state.custom_events[index]
            return None, 204
    return None, 204  # idempotent like the HC3: deleting an absent event is fine


def custom_event_publish(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # GET /customEvents/{name}/publish — the HC3's second fire endpoint.
    # Live HC3 (5.221): fires 204 even for a valid-but-unknown name (no
    # existence check); 501 for invalid names.
    name = req.path_params["name"]
    if VARIABLE_NAME_RE.fullmatch(name) is None:
        return None, 501
    if _custom_event(state, name) is not None:
        state.record_event(name)
        if req.emit is not None:
            req.emit(messages.custom_event(name))
    return None, 204
