"""Plugins category: QA devices, variable storage, child devices, views.

The status contract for variables mirrors the HC3 so quickapp.lua's
fallback logic works: PUT on a missing variable returns 404 (the lib then
POSTs to create it), PUT on an existing one returns 204.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ... import messages
from ..request import ApiRequest, forward_to_proxy
from ..state import SimState, public

logger = logging.getLogger(__name__)


def _now(req: ApiRequest) -> float:
    return req.clock.time if req.clock is not None else time.time()


def plugins_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    plugins = [d for d in state.devices.values() if state.is_plugin_device(d)]
    return public(sorted(plugins, key=lambda d: d["id"])), 200


def plugin_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    return (public(dev), 200) if dev is not None else (None, 404)


def _variables(state: SimState, dev: dict[str, Any]) -> dict[str, dict[str, Any]]:
    # plugin variables live outside the device shape (the real HC3 has no
    # top-level "variables" field — the compat oracle caught it)
    return state.plugin_variables.setdefault(dev["id"], {})


def variables_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    variables = sorted(_variables(state, dev).values(), key=lambda v: v["name"])
    return public(variables), 200


def variable_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    var = _variables(state, dev).get(req.path_params["key"])
    return (public(var), 200) if var is not None else (None, 404)


def _var_from_body(req: ApiRequest, default_name: str | None = None) -> dict[str, Any] | None:
    if not isinstance(req.body, dict):
        return None
    name = req.body.get("name", default_name)
    if not isinstance(name, str) or not name:
        return None
    return {
        "name": name,
        "value": req.body.get("value"),
        "isHidden": bool(req.body.get("isHidden", False)),
    }


def variable_put(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    variables = _variables(state, dev)
    key = req.path_params["key"]
    if key not in variables:
        return None, 404  # drives quickapp.lua's PUT -> POST fallback
    spec = _var_from_body(req, default_name=key)
    if spec is None:
        return None, 400
    if state.is_proxy(dev["id"]):
        # the HC3 owns the device; its own event comes back via the poll
        variables[key] = spec
        forward_to_proxy(req, True)
        return None, 204
    entry = state.record_property_event(
        dev["id"], key, spec["value"], variables[key].get("value"), _now(req)
    )
    if entry is not None and req.emit is not None:
        req.emit(messages.refresh_state_event(entry))
    variables[key] = spec
    return None, 204


def variable_post(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    spec = _var_from_body(req)
    if spec is None:
        return None, 400
    variables = _variables(state, dev)
    if state.is_proxy(dev["id"]):
        variables[spec["name"]] = spec
        forward_to_proxy(req, True)
        return public(spec), 201
    entry = state.record_property_event(
        dev["id"],
        spec["name"],
        spec["value"],
        variables.get(spec["name"], {}).get("value"),
        _now(req),
    )
    if entry is not None and req.emit is not None:
        req.emit(messages.refresh_state_event(entry))
    variables[spec["name"]] = spec
    return public(spec), 201


def variable_delete(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    variables = _variables(state, dev)
    key = req.path_params["key"]
    if key not in variables:
        return None, 404
    del variables[key]
    forward_to_proxy(req, state.is_proxy(dev["id"]))
    return None, 204


def variables_clear(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    _variables(state, dev).clear()
    forward_to_proxy(req, state.is_proxy(dev["id"]))
    return None, 204


def child_device_create(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    if not isinstance(req.body, dict) or not req.body.get("name") or "parentId" not in req.body:
        return None, 400
    if state.device(req.body.get("parentId")) is None:
        return None, 404
    if state.is_proxy(int(req.body["parentId"])):
        # the HC3 owns the parent: create the child there and shadow it
        # under the HC3-assigned id, so callbacks route to the right device
        if req.remote is None:
            return None, 404
        child, status = req.remote(req.method, req.path, req.body)
        if not isinstance(child, dict) or child.get("id") is None:
            return None, 400
        state.register_proxy_child(child)
        return public(child), 201
    dev = state.create_child_device(int(req.body["parentId"]), req.body)
    return dev, 201


def plugin_update_property(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    if not isinstance(req.body, dict):
        return None, 400
    dev = state.device(req.body.get("deviceId"))
    if dev is None:
        return None, 404
    name = req.body.get("propertyName")
    if not isinstance(name, str):
        return None, 400
    properties = dev.setdefault("properties", {})
    old = properties.get(name)
    properties[name] = req.body.get("value")
    dev["modified"] = int(_now(req))
    if state.is_proxy(dev["id"]):
        # the HC3 owns the device: push the update there and DON'T emit a
        # local refresh event — the HC3 proxy emits DevicePropertyUpdatedEvent
        # and the poll mirrors it back (plua caveat 1: exactly one event)
        forward_to_proxy(req, True)
        return None, 204
    entry = state.record_property_event(dev["id"], name, req.body.get("value"), old, _now(req))
    if entry is not None and req.emit is not None:
        req.emit(messages.refresh_state_event(entry))
    return None, 204


def plugin_update_view(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    if not isinstance(req.body, dict):
        return None, 400
    dev = state.device(req.body.get("deviceId"))
    if dev is None:
        return None, 404
    view = dev.get("view")
    if not isinstance(view, dict):
        view = {}  # catalog skeletons carry a list-shaped template view
        dev["view"] = view
    component = view.setdefault(str(req.body.get("componentName", "")), {})
    component[str(req.body.get("propertyName", ""))] = req.body.get("newValue")
    forward_to_proxy(req, state.is_proxy(dev["id"]))
    return None, 204


def plugin_update_interfaces(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    if not isinstance(req.body, dict):
        return None, 400
    dev = state.device(req.body.get("deviceId"))
    if dev is None:
        return None, 404
    action = req.body.get("action")
    interfaces = req.body.get("interfaces")
    if action not in ("add", "remove") or not isinstance(interfaces, (list, tuple)):
        return None, 400
    current = dev.setdefault("interfaces", [])
    for interface in interfaces:
        if action == "add" and interface not in current:
            current.append(interface)
        elif action == "remove" and interface in current:
            current.remove(interface)
    forward_to_proxy(req, state.is_proxy(dev["id"]))
    return None, 204


def plugin_restart(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # HC3 restarts the plugin process; flua QAs run cooperatively, so a real
    # restart is not implemented yet — accept and note it.
    logger.warning("plugin restart requested for %r: simulated (QA keeps running)", req.body)
    # a proxy-mode QA owns a real plugin on the HC3: restart that one too
    if isinstance(req.body, dict) and state.is_proxy(req.body.get("deviceId")):
        forward_to_proxy(req, True)
    return None, 204


def ui_event_call(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    """GET or POST /plugins/callUIEvent — deliver a UI interaction to a QA device.

    Mirrors the real HC3 endpoint and pumps a ``uiEvent`` message to the QA,
    which routes it through the QA's uiCallbacks like a tap on the real UI
    would. GET (query params) is the viewer's channel; POST (JSON body) is
    what a proxy device on the HC3 uses to send interactions back.
    """
    body = req.body if isinstance(req.body, dict) else {}

    def field(key: str) -> Any:
        value = body.get(key)
        if value is None:
            value = req.query.get(key)
        return value

    try:
        device_id = int(field("deviceID") or field("deviceId") or "")
    except (TypeError, ValueError):
        return None, 400
    element_name = field("elementName")
    event_type = field("eventType")
    if not element_name or not event_type:
        return None, 400
    value = field("value")
    values = body.get("values")
    if value is None and isinstance(values, (list, tuple)):
        # multi selects arrive as a list; join them — the Lua handler splits
        # the single value param back into the list
        value = ",".join(str(entry) for entry in values)
    if req.emit is not None:
        req.emit(messages.ui_event(device_id, element_name, event_type, value))
    return None, 200
