"""Proxy mode: mirror a flua QA onto the real HC3 (plua's ``proxy.lua`` in Python).

When a QA carries ``--%%proxy:true`` (online mode only), flua deploys a proxy
QuickApp on the HC3 named ``<QA name>_Proxy`` with the same device type as the
emulated QA. The proxy funnels every device action and UI event back to the
emulator over plain HTTP, and flua pushes property/view updates to the proxy so
it always reflects the emulated QA's state. The emulated QA runs with the
proxy's HC3 device id, so the two are treated as one device (plua caveat 2).

The HC3 side is the standard plua proxy QuickApp (``PROXY_LUA``): a CONNECT
action stores the emulator's ip:port (in internal storage, so it survives
proxy restarts), an actionHandler forwards every action to
``http://ip:port/api/devices/<id>/action/<name>``, a UIHandler forwards UI
events to ``http://ip:port/api/plugins/callUIEvent``, and initChildDevices is
stubbed out (children are created by the emulator through createChildDevice).

Reuse: an existing ``<name>_Proxy`` on the HC3 is kept as-is (duplicates are
deleted, newest wins; a proxy of the wrong type is deleted and recreated).
"""

from __future__ import annotations

import base64
import json
import logging
import socket
import urllib.parse
from typing import TYPE_CHECKING, Any

from . import messages
from .api.state import DEFAULT_DEVICE_TYPE
from .devices import skeleton_for
from .ui import compile_ui

if TYPE_CHECKING:
    from .engine import LuaEngine

logger = logging.getLogger(__name__)

# The emulator's callback port (the HC3 proxy posts actions/UI events here).
# Overridable through the environment chain: FLUA_PROXY_PORT.
PROXY_PORT_DEFAULT = 8080

# The QuickApp code installed on the HC3 proxy device. Standard plua proxy:
# the only device-specific bits are the name and the type, which live in the
# .fqa envelope, not in this code.
PROXY_LUA = r"""-- flua proxy QuickApp (installed by --%%proxy:true)
local ip, port = nil, nil
local actionUrl, uiUrl = "", ""

function QuickApp:onInit()
  self:debug("Started", self.name, self.id)
  local con = self:internalStorageGet("con") or {}
  ip, port = con.ip, con.port
  if ip and port then
    actionUrl = "http://" .. ip .. ":" .. port .. "/api/devices/%s/action/%s"
    uiUrl = "http://" .. ip .. ":" .. port .. "/api/plugins/callUIEvent"
  end
end

-- Actions the proxy handles itself rather than forwarding to the emulator
local IGNORE = { MEMORYWATCH = true, APIFUN = true, CONNECT = true }

-- Store where the emulator listens for callbacks (survives proxy restarts)
function QuickApp:CONNECT(con)
  con = con or {}
  self:internalStorageSet("con", con)
  ip, port = con.ip, con.port
  if ip and port then
    actionUrl = "http://" .. ip .. ":" .. port .. "/api/devices/%s/action/%s"
    uiUrl = "http://" .. ip .. ":" .. port .. "/api/plugins/callUIEvent"
  end
  self:debug("Connected to emulator at " .. tostring(ip) .. ":" .. tostring(port))
end

-- Forward every device action to the emulator (special actions stay local)
function QuickApp:actionHandler(action)
  if IGNORE[action.actionName] then
    return self:callAction(action.actionName, table.unpack(action.args or {}))
  end
  if not actionUrl then self:error("proxy not connected to emulator") return end
  local data = { args = action.args or {} }
  net.HTTPClient():request(string.format(actionUrl, action.deviceId, action.actionName), {
    options = {
      method = "POST",
      headers = { ["Content-Type"] = "application/json" },
      data = json.encode(data),
    },
    success = function(resp) print("success", resp.status) end,
    error = function(err) self:error(err) end,
  })
end

-- Forward UI events to the emulator
function QuickApp:UIHandler(ev)
  if not uiUrl then self:error("proxy not connected to emulator") return end
  local data = {
    deviceID = ev.deviceId or ev.deviceID,
    eventType = ev.eventType,
    elementName = ev.elementName,
    value = ev.value,
    values = ev.values,
  }
  net.HTTPClient():request(uiUrl, {
    options = {
      method = "POST",
      headers = { ["Content-Type"] = "application/json" },
      data = json.encode(data),
    },
    success = function(resp) print("success", resp.status) end,
    error = function(err) self:error(err) end,
  })
end

-- Children are created by the emulator through /plugins/createChildDevice
function QuickApp:initChildDevices(_) end
"""


def local_ip() -> str:
    """The LAN address the HC3 proxy should call back to (plua's get_local_ip).

    UDP-connects to a public address to learn the outbound interface, then
    falls back to the hostname, then loopback. Never sends actual data.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _proxy_ui(device_properties: dict[str, Any]) -> tuple[Any, Any, Any]:
    """The UI structures for the proxy's initial properties.

    Reuses the QA's compiled --%%u structures; a QA without UI gets the
    empty UI shapes (the HC3 expects the three properties present).
    """
    callbacks = device_properties.get("uiCallbacks")
    layout = device_properties.get("viewLayout")
    view = device_properties.get("uiView")
    if callbacks is None or layout is None or view is None:
        empty = compile_ui([], 0)
        return (
            callbacks if callbacks is not None else empty["uiCallbacks"],
            layout if layout is not None else empty["viewLayout"],
            view if view is not None else empty["uiView"],
        )
    return callbacks, layout, view


def build_proxy_fqa(
    name: str,
    device_type: str | None,
    device_properties: dict[str, Any],
    interfaces: list[str] | None,
) -> dict[str, Any]:
    """The .fqa package for the HC3 proxy device (same shape as qa_export)."""
    ui_callbacks, view_layout, ui_view = _proxy_ui(device_properties)
    properties: dict[str, Any] = {
        "apiVersion": "1.3",
        # variables arrive right after boot through updateProperty (they are
        # evaluated by the QA bootstrap, not parseable here)
        "quickAppVariables": [],
        "viewLayout": view_layout,
        "uiView": ui_view,
        "uiCallbacks": ui_callbacks,
        "useUiView": bool(device_properties.get("useUiView", True)),
        "typeTemplateInitialized": True,
    }
    return {
        "apiVersion": "1.3",
        "name": f"{name}_Proxy",
        "type": device_type or DEFAULT_DEVICE_TYPE,
        "initialProperties": properties,
        "initialInterfaces": [i for i in (interfaces or []) if i != "quickApp"],
        "files": [
            {
                "name": "main",
                "isMain": True,
                "isOpen": False,
                "type": "lua",
                "content": PROXY_LUA,
            }
        ],
    }


def deploy_proxy(
    engine: LuaEngine,
    name: str,
    device_type: str,
    device_properties: dict[str, Any],
) -> dict[str, Any] | None:
    """Upload the proxy QuickApp to the HC3 and return the created device."""
    skeleton = skeleton_for(device_type)
    if skeleton is None:
        raise ValueError(f"unknown device type: {device_type!r}")
    fqa = build_proxy_fqa(name, device_type, device_properties, skeleton.get("interfaces") or [])
    raw = json.dumps(fqa).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    device, status = engine.api.dispatch_hc3("POST", "/quickApp", {"file": encoded})
    if status not in (200, 201) or not isinstance(device, dict):
        return None
    device["id"] = int(device["id"])  # plua: math.floor(device.id)
    return device


def existing_proxy(engine: LuaEngine, proxy_name: str, device_type: str) -> dict[str, Any] | None:
    """Find an existing proxy on the HC3.

    Several proxies with the same name: keep the newest, delete the others.
    A proxy of the wrong type is deleted (the HC3 cannot change a device's
    type) and None is returned so the caller deploys a fresh one.
    """
    quoted = urllib.parse.quote(proxy_name)
    proxies, status = engine.api.dispatch_hc3("GET", f"/devices?name={quoted}")
    if status != 200 or not isinstance(proxies, list) or not proxies:
        return None
    proxies = sorted(proxies, key=lambda dev: int(dev.get("id") or 0), reverse=True)
    for old in proxies[1:]:  # duplicates: keep only the newest
        engine.post(
            messages.log("info", f"flua: old proxy deleted: {old.get('id')} {old.get('name')}")
        )
        engine.api.dispatch_hc3("DELETE", f"/devices/{int(old['id'])}")
    device = proxies[0]
    if device.get("type") != device_type:
        engine.post(
            messages.log(
                "info",
                f"flua: existing proxy of wrong type, deleted: "
                f"{device.get('id')} {device.get('name')}",
            )
        )
        engine.api.dispatch_hc3("DELETE", f"/devices/{int(device['id'])}")
        return None
    device["id"] = int(device["id"])
    engine.post(
        messages.log("info", f"flua: existing proxy found: {device.get('id')} {device.get('name')}")
    )
    return device


def sync_proxy_ui(
    engine: LuaEngine,
    device_id: int,
    device_properties: dict[str, Any],
    use_ui_view: Any = None,
) -> None:
    """Push the QA's current UI structures to an existing proxy.

    The user may have edited the --%%u directives since the proxy was
    deployed, so every connect refreshes the HC3 device's UI properties —
    plua's updateQAparts/UI mechanism, applied always instead of behind a
    --%%proxyupdate flag. One PUT /devices/{id} with the properties object;
    the HC3 emits the property events and the poll mirrors them back
    (caveat 1: no local duplicates).

    ``useUiView`` is only pushed when the QA declares it (--%%useUiView):
    otherwise the proxy keeps whatever the user configured on the HC3 — the
    legacy viewLayout is still common there.
    """
    callbacks, layout, view = _proxy_ui(device_properties)
    properties: dict[str, Any] = {
        "viewLayout": layout,
        "uiView": view,
        "uiCallbacks": callbacks,
    }
    if use_ui_view is not None:
        properties["useUiView"] = bool(use_ui_view)
    _data, status = engine.api.dispatch_hc3(
        "PUT",
        f"/devices/{int(device_id)}",
        {"properties": properties},
    )
    if status not in (200, 204):
        logger.warning(
            "proxy UI sync failed (HTTP %s): the HC3 proxy may show a stale UI",
            status,
        )


def register_proxy_children(engine: LuaEngine, device_id: int) -> None:
    """Shadow an existing proxy's HC3 children in the sim under their HC3 ids.

    Fibaro's design routes every child action/UI event through the parent
    (our proxy), which funnels them back to the emulator. The emulated QA
    finds its children with ``api.get("/devices?parentId="..self.id)`` and
    builds QuickAppChild instances for them, so shadow children must exist
    locally with the same deviceIds (plua's existingProxy child loop) — they
    are pure data: the place property updates land and callbacks route to.
    """
    children, status = engine.api.dispatch_hc3("GET", f"/devices?parentId={int(device_id)}")
    if status != 200 or not isinstance(children, list):
        logger.warning(
            "cannot list proxy children (HTTP %s): the emulated QA will not see them",
            status,
        )
        return
    for child in children:
        if not isinstance(child, dict) or child.get("id") is None:
            continue
        engine.api.state.register_proxy_child(child)
        engine.post(
            messages.log(
                "info",
                f"flua: existing child proxy found: {child.get('id')} {child.get('name')}",
            )
        )


def resolve_proxy(
    engine: LuaEngine,
    name: str,
    device_type: str | None,
    device_properties: dict[str, Any],
    use_ui_view: Any = None,
) -> dict[str, Any]:
    """Reuse the existing proxy or deploy a new one; raises on HC3 failure."""
    resolved_type = device_type or DEFAULT_DEVICE_TYPE
    # validate the type before any HC3 traffic (register_qa's own contract)
    if skeleton_for(resolved_type) is None:
        raise ValueError(f"unknown device type: {resolved_type!r}")
    proxy_name = f"{name}_Proxy"
    device = existing_proxy(engine, proxy_name, resolved_type)
    if device is None:
        device = deploy_proxy(engine, name, resolved_type, device_properties)
        if device is None:
            raise ValueError(f"cannot create proxy {proxy_name} on the HC3")
        engine.post(messages.log("info", f"flua: proxy installed: {device.get('id')} {proxy_name}"))
    else:
        # the proxy is reused, but the QA's UI may have changed since it was
        # deployed — refresh its viewLayout/uiView/uiCallbacks (useUiView only
        # when the QA declares it, so the HC3's own setting is respected)
        sync_proxy_ui(engine, device["id"], device_properties, use_ui_view)
        # shadow the proxy's existing children before the QA boots, so
        # api.get("/devices?parentId=...") finds them under their HC3 ids
        register_proxy_children(engine, device["id"])
        engine.post(messages.log("info", f"flua: proxy UI synced: {device.get('id')} {proxy_name}"))
    return device


def connect_proxy(engine: LuaEngine, device_id: int, ip: str, port: int) -> tuple[Any, int]:
    """Tell the proxy where the emulator listens for callbacks."""
    return engine.api.dispatch_hc3(
        "POST",
        f"/devices/{int(device_id)}/action/CONNECT",
        {"args": [{"ip": ip, "port": int(port)}]},
    )
