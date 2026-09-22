"""Wire format for flua messages.

Every message is a plain dict with a string ``"type"`` field and a payload of
JSON-compatible values only (str, int, float, bool, None, list, dict).
Functions never cross the bridge — Lua callbacks are addressed by integer IDs
that the Lua side registers in ``init.lua``.

Keeping the format JSON-compatible means the same messages could travel over
any transport (thread queue, pipe, socket, subprocess) if the engine ever
grows one — the asyncio side can stay identical.
"""

from typing import Any

# --- Lua -> Python (inbound, posted by _PY.post) -----------------------------

SET_TIMEOUT = "setTimeout"  # {"id": int, "delay": int, "qa": int?}  ms + QA attribution
HTTP_REQUEST = (
    "httpRequest"  # {"id": int, "qa": int?, "url": str, "method": str,
    # "headers": dict?, "data": str?, "timeout": number?}
)
TCP_CONNECT = "tcpConnect"  # {"id": int, "qa": int?, "host": str, "port": int, "timeout": number?}
TCP_SEND = "tcpSend"  # {"id": int, "qa": int?, "conn": int, "data": str}
TCP_READ = (
    "tcpRead"  # {"id": int, "qa": int?, "conn": int, "pattern"?: "*l"|"*a"|int, "delimiter"?: str}
)
UDP_SEND = "udpSend"  # {"id": int, "qa": int?, "conn": int, "data": str, "ip": str, "port": int}
UDP_RECEIVE = "udpReceive"  # {"id": int, "qa": int?, "conn": int}
WS_CONNECT = "wsConnect"  # {"id": int, "qa": int?, "conn": int, "url": str, "timeout"?: number}
WS_SEND = "wsSend"  # {"id": int, "qa": int?, "conn": int, "data": str}
MQTT_CONNECT = "mqttConnect"  # {"qa": int?, "conn": int, "uri": str, "options": dict}
MQTT_SUBSCRIBE = (
    "mqttSubscribe"  # {"qa": int?, "conn": int, "packetId": int, "topics": [[topic, qos], ...]}
)
MQTT_UNSUBSCRIBE = "mqttUnsubscribe"  # {"qa": int?, "conn": int, "packetId": int, "topics": [...]}
MQTT_PUBLISH = (
    "mqttPublish"  # {"qa": int?, "conn": int, "packetId": int, "topic": str,
    # "payload": str, "qos": int, "retain": bool}
)
MQTT_DISCONNECT = "mqttDisconnect"  # {"qa": int?, "conn": int}
CLEAR_TIMEOUT = "clearTimeout"  # {"id": int}
LOG = "log"  # {"level": "info|warning|error", "text": str}
EXIT = "exit"  # {"code": int}
QA_LOADED = "qaLoaded"  # {"id": int}  a QA finished loading its code

# --- Python -> Lua (outbound, delivered via _PY.dispatch) --------------------

TIMER_EXPIRED = "timerExpired"  # {"id": int}  run registered callback id
START_QA = "startQA"  # {"id": int, "path": str, "config": dict, "arg0": str}
HTTP_RESULT = (
    "httpResult"  # {"id": int, "qa": int?, "status": int?, "data": str?,
    # "headers": dict?, "error": str?}
)
TCP_RESULT = (
    "tcpResult"  # {"id": int, "qa": int?, "ok": bool, "conn"?: int, "data"?: str, "err"?: str}
)
UDP_RESULT = "udpResult"  # {"id": int, "qa": int?, "ok": bool, "data"?: str, "err"?: str}
WS_EVENT = "wsEvent"  # {"qa": int, "conn": int, "event": str, "data"?: str}
MQTT_EVENT = "mqttEvent"  # {"qa": int, "conn": int, "event": str, "data"?: dict}
REFRESH_STATE_EVENT = (
    "refreshStateEvent"  # {"event": {...}}  pump-delivered to RefreshStateSubscribers
)
RUN_PREAMBLE = "runPreamble"  # {"code": str}  -e bootstrap runs in the main Lua state
RESTART_QA = (
    "restartQA"  # {"id": int, "path": str, "config": dict, "files": [{name,path}], "arg0": str}
)
QA_VARS = "qaVars"  # {"id": int, "vars": {name: value}}  evaluated --%%var values
DEVICE_ACTION = "deviceAction"  # {"id": int, "action": str, "args": list}
UI_EVENT = "uiEvent"  # {"deviceId": int, "elementName": str, "eventType": str, "value"?: str}
CUSTOM_EVENT = "customEvent"  # {"name": str}


def set_timeout(timer_id: int, delay_ms: int, qa: int | None = None) -> dict[str, Any]:
    """Build a setTimeout request. ``timer_id`` doubles as the Lua callback id.

    ``qa`` attributes the timer to a QA (nil = runtime/untracked).
    """
    msg: dict[str, Any] = {"type": SET_TIMEOUT, "id": timer_id, "delay": delay_ms}
    if qa is not None:
        msg["qa"] = qa
    return msg


def clear_timeout(timer_id: int) -> dict[str, Any]:
    return {"type": CLEAR_TIMEOUT, "id": timer_id}


def log(level: str, text: str) -> dict[str, Any]:
    return {"type": LOG, "level": level, "text": text}


def exit_msg(code: int = 0) -> dict[str, Any]:
    return {"type": EXIT, "code": code}


def timer_expired(timer_id: int) -> dict[str, Any]:
    return {"type": TIMER_EXPIRED, "id": timer_id}


def start_qa_msg(qa_id: int, path: str, config: dict[str, Any], arg0: str) -> dict[str, Any]:
    """Bootstrap a dynamically loaded QA (delivered via the pump, so the
    engine never calls into Lua while Lua is on the stack)."""
    files = [{"name": f["name"], "path": f["path"]} for f in config.get("files") or []]
    return {
        "type": START_QA,
        "id": int(qa_id),
        "path": path,
        "config": config,
        "files": files,
        "arg0": arg0,
    }


def http_result(
    request_id: int,
    qa: int | None,
    status: int | None = None,
    data: str | None = None,
    headers: dict[str, str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Response for a net.HTTPClient request: status/data/headers or error."""
    msg: dict[str, Any] = {"type": HTTP_RESULT, "id": int(request_id)}
    if qa is not None:
        msg["qa"] = qa
    if error is not None:
        msg["error"] = error
    else:
        msg["status"] = status
        msg["data"] = data
        msg["headers"] = headers or {}
    return msg


def tcp_result(
    request_id: int,
    qa: int | None,
    ok: bool,
    conn: int | None = None,
    data: str | None = None,
    err: str | None = None,
) -> dict[str, Any]:
    """Result for a net.TCPSocket operation: connect returns conn, reads
    return data, failures carry err."""
    msg: dict[str, Any] = {"type": TCP_RESULT, "id": int(request_id), "ok": bool(ok)}
    if qa is not None:
        msg["qa"] = qa
    if ok:
        if conn is not None:
            msg["conn"] = conn
        if data is not None:
            msg["data"] = data
    else:
        msg["err"] = err or "error"
    return msg


def udp_result(
    request_id: int,
    qa: int | None,
    ok: bool,
    data: str | None = None,
    err: str | None = None,
) -> dict[str, Any]:
    """Result for a net.UDPSocket operation: receive returns data, sendTo
    just reports ok, failures carry err."""
    msg: dict[str, Any] = {"type": UDP_RESULT, "id": int(request_id), "ok": bool(ok)}
    if qa is not None:
        msg["qa"] = qa
    if ok:
        if data is not None:
            msg["data"] = data
    else:
        msg["err"] = err or "error"
    return msg


def ws_event(qa: int, conn: int, event: str, data: str | None = None) -> dict[str, Any]:
    """A net.WebSocketClient event: connected/disconnected/error/dataReceived."""
    msg: dict[str, Any] = {"type": WS_EVENT, "qa": int(qa), "conn": int(conn), "event": event}
    if data is not None:
        msg["data"] = data
    return msg


def mqtt_event(qa: int, conn: int, event: str, data: Any = None) -> dict[str, Any]:
    """An mqtt.* client event: connected/subscribed/message/.../opDone."""
    msg: dict[str, Any] = {"type": MQTT_EVENT, "qa": int(qa), "conn": int(conn), "event": event}
    if data is not None:
        msg["data"] = data
    return msg


def restart_qa_msg(qa_id: int, path: str, config: dict[str, Any], arg0: str) -> dict[str, Any]:
    """Re-run a QA's code (files changed): extras load first, main last."""
    files = [{"name": f["name"], "path": f["path"]} for f in config.get("files") or []]
    return {
        "type": RESTART_QA,
        "id": int(qa_id),
        "path": path,
        "config": config,
        "files": files,
        "arg0": arg0,
    }


def refresh_state_event(entry: dict[str, Any]) -> dict[str, Any]:
    """A refreshStates event for the Lua RefreshStateSubscribers (delivered
    through the pump, not via direct bridge calls)."""
    return {"type": REFRESH_STATE_EVENT, "event": entry}


def run_preamble(code: str) -> dict[str, Any]:
    """A -e debugger bootstrap: run in the MAIN Lua state (not as a QA), so
    the VS Code mobdebug preamble does not consume a QA id."""
    return {"type": RUN_PREAMBLE, "code": code}


def device_action(device_id: int, action: str, args: list[Any] | None = None) -> dict[str, Any]:
    """Run ``action`` on a QA device's QuickApp (via its callAction)."""
    return {
        "type": DEVICE_ACTION,
        "id": int(device_id),
        "action": action,
        "args": list(args or []),
    }


def custom_event(name: str) -> dict[str, Any]:
    """Deliver a custom event to QAs that define onCustomEvent."""
    return {"type": CUSTOM_EVENT, "name": name}


def ui_event(
    device_id: int, element_name: str, event_type: str, value: str | None = None
) -> dict[str, Any]:
    """Deliver a UI interaction to a QA device — the message behind the
    real HC3's GET /plugins/callUIEvent endpoint."""
    msg: dict[str, Any] = {
        "type": UI_EVENT,
        "deviceId": int(device_id),
        "elementName": element_name,
        "eventType": event_type,
    }
    if value is not None:
        msg["value"] = value
    return msg
