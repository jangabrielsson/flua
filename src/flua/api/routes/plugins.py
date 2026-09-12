"""Plugins category: QA devices, variable storage, child devices, views.

The status contract for variables mirrors the HC3 so quickapp.lua's
fallback logic works: PUT on a missing variable returns 404 (the lib then
POSTs to create it), PUT on an existing one returns 204.
"""

from __future__ import annotations

import logging
from typing import Any

from ..request import ApiRequest
from ..state import SimState, public

logger = logging.getLogger(__name__)


def plugins_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    plugins = [d for d in state.devices.values() if state.is_plugin_device(d)]
    return public(sorted(plugins, key=lambda d: d["id"])), 200


def plugin_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    return (public(dev), 200) if dev is not None else (None, 404)


def _variables(dev: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dev.setdefault("variables", {})


def variables_list(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    variables = sorted(_variables(dev).values(), key=lambda v: v["name"])
    return public(variables), 200


def variable_get(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    var = _variables(dev).get(req.path_params["key"])
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
    variables = _variables(dev)
    key = req.path_params["key"]
    if key not in variables:
        return None, 404  # drives quickapp.lua's PUT -> POST fallback
    spec = _var_from_body(req, default_name=key)
    if spec is None:
        return None, 400
    state.record_change(dev["id"], key, spec["value"], variables[key].get("value"))
    variables[key] = spec
    return None, 204


def variable_post(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    spec = _var_from_body(req)
    if spec is None:
        return None, 400
    variables = _variables(dev)
    state.record_change(dev["id"], spec["name"], spec["value"], variables.get(spec["name"], {}).get("value"))
    variables[spec["name"]] = spec
    return public(spec), 201


def variable_delete(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    variables = _variables(dev)
    key = req.path_params["key"]
    if key not in variables:
        return None, 404
    del variables[key]
    return None, 204


def variables_clear(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    dev = state.plugin(req.path_params["id"])
    if dev is None:
        return None, 404
    _variables(dev).clear()
    return None, 204


def child_device_create(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    if not isinstance(req.body, dict) or not req.body.get("name") or "parentId" not in req.body:
        return None, 400
    if state.device(req.body.get("parentId")) is None:
        return None, 404
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
    state.record_change(dev["id"], name, req.body.get("value"), old)
    return None, 204


def plugin_update_view(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    if not isinstance(req.body, dict):
        return None, 400
    dev = state.device(req.body.get("deviceId"))
    if dev is None:
        return None, 404
    view = dev.setdefault("view", {})
    component = view.setdefault(str(req.body.get("componentName", "")), {})
    component[str(req.body.get("propertyName", ""))] = req.body.get("newValue")
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
    return None, 204


def plugin_restart(state: SimState, req: ApiRequest) -> tuple[Any, int]:
    # HC3 restarts the plugin process; flua QAs run cooperatively, so a real
    # restart is not implemented yet — accept and note it.
    logger.warning("plugin restart requested for %r: simulated (QA keeps running)", req.body)
    return None, 204