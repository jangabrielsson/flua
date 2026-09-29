"""QuickApp UI: ``--%%u`` rows -> uiCallbacks + viewLayout + uiView.

Port of the QuickApp UI compiler
(extendUI/UI2uiCallbacks/mkViewLayout/UI2NewUiView). The row format: one
directive per row, one dict per element
(``{button="name", text=...}``, ``{slider=...}``, ``{label=...}``,
``{switch=...}``, ``{select=...}``, ``{multi=...}``), or a list of element
dicts for several elements on one row.

The two output structures match the HC3's device properties:

- ``viewLayout`` — the legacy ``$jason`` format.
- ``uiView`` — the newer component format (rows of ``horizontal`` rows with
  typed components and device-action event bindings).
- ``uiCallbacks`` — {name, eventType, callback} entries so the HC3 (and
  flua's QuickApp runtime) can route UI events to QA methods.

``useUiView`` (device property) picks which of the two the UI renders; flua
sets it true by default, ``--%%useUiView:false`` forces the legacy layout.
"""

from typing import Any

# Per-element weight by row size in the uiView format (the exact table).
_UI_VIEW_WEIGHTS = {1: "1.0", 2: "0.5", 3: "0.25", 4: "0.33", 5: "0.20"}

_ELEMENT_KEYS = ("button", "slider", "label", "select", "switch", "multi")


def compile_ui(rows: list[Any], device_id: int) -> dict[str, Any]:
    """Compile parsed ``--%%u`` rows into the HC3 UI property structures.

    ``rows`` is ``config["u"]``: one entry per directive, each a dict
    (single element) or list of dicts (several elements on the row).
    """
    normalized: list[list[dict[str, Any]]] = []
    for row in rows:
        normalized.append([dict(row)] if isinstance(row, dict) else [dict(e) for e in row])
    _apply_defaults(normalized)
    return {
        "uiCallbacks": _callbacks(normalized),
        "viewLayout": _view_layout(normalized, device_id),
        "uiView": _ui_view(normalized),
    }


def _type_of(el: dict[str, Any]) -> str:
    for key in _ELEMENT_KEYS:
        if key in el:
            return key
    raise ValueError(f"UI element without a type key: {sorted(el)!r}")


def _apply_defaults(rows: list[list[dict[str, Any]]]) -> None:
    """extendUI port: normalize every element (type/id/text/visible defaults,
    stringified slider bounds, switch value)."""
    for row in rows:
        for el in row:
            typ = _type_of(el)
            el["type"] = typ
            el["id"] = el[typ]
            el.setdefault("text", "")
            if typ == "button":
                el.setdefault("onReleased", "")
                el.setdefault("onLongPressDown", "")
                el.setdefault("onLongPressReleased", "")
                el.setdefault("visible", True)
            elif typ == "switch":
                el.setdefault("value", "false")
                el.setdefault("onReleased", "")
                el.setdefault("visible", True)
            elif typ == "slider":
                el.setdefault("onChanged", "")
                el["value"] = str(el.get("value", "0"))
                el["min"] = str(el.get("min", "0"))
                el["max"] = str(el.get("max", "100"))
                el["step"] = str(el.get("step", "1"))
                el.setdefault("visible", True)
            elif typ == "label":
                el.setdefault("visible", True)
            elif typ == "select":
                el.setdefault("onToggled", "")
                el.setdefault("visible", True)
                el.setdefault("options", [])
                el.setdefault("value", "")
            elif typ == "multi":
                el.setdefault("onToggled", "")
                el.setdefault("visible", True)
                el.setdefault("options", [])
                el.setdefault("values", [])


def _callbacks(rows: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """UI2uiCallbacks port: {name, eventType, callback} entries."""
    callbacks: list[dict[str, Any]] = []
    for row in rows:
        for el in row:
            typ, name = el["type"], el["id"]
            if typ in ("button", "switch"):
                for event in ("onReleased", "onLongPressDown", "onLongPressReleased"):
                    callbacks.append(
                        {"callback": el.get(event, ""), "eventType": event, "name": name}
                    )
            elif typ == "slider":
                callbacks.append(
                    {"callback": el.get("onChanged", ""), "eventType": "onChanged", "name": name}
                )
            elif typ in ("select", "multi"):
                callbacks.append(
                    {"callback": el.get("onToggled", ""), "eventType": "onToggled", "name": name}
                )
    return callbacks


def _options(el: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(option, type="option") for option in el.get("options") or []]


def _layout_element(el: dict[str, Any], weight: str) -> dict[str, Any]:
    """ELMS port: one legacy viewLayout component."""
    typ, name = el["type"], el["id"]
    style_weight = el.get("weight") or weight or "0.50"
    if typ == "button":
        return {
            "name": name,
            "visible": True,
            "style": {"weight": style_weight},
            "text": el["text"],
            "type": "button",
        }
    if typ in ("select", "multi"):
        return {
            "name": name,
            "style": {"weight": style_weight},
            "text": el["text"],
            "type": "select",
            "visible": True,
            "selectionType": "single" if typ == "select" else "multi",
            "options": _options(el),
            "values": list(el.get("values") or []),
        }
    if typ == "switch":
        return {
            "name": name,
            "visible": True,
            "style": {"weight": style_weight},
            "text": el["text"],
            "type": "switch",
            "value": el["value"],
        }
    if typ == "slider":
        return {
            "name": name,
            "visible": True,
            "step": el["step"],
            "value": el["value"],
            "max": el["max"],
            "min": el["min"],
            "style": {"weight": style_weight},
            "text": el["text"],
            "type": "slider",
        }
    # label
    return {
        "name": name,
        "visible": True,
        "style": {"weight": style_weight},
        "text": el["text"],
        "type": "label",
    }


def _layout_row(row: list[dict[str, Any]]) -> dict[str, Any]:
    """mkRow port: one legacy viewLayout row (vertical, trailing space)."""
    components: list[dict[str, Any]] = []
    if len(row) > 1:
        width = f"{1 / len(row):.2f}"
        if width.endswith(".00"):
            width = width[:-3]  # strip a trailing ".00"
        inner = [_layout_element(el, width) for el in row]
        components.append({"components": inner, "style": {"weight": "1.2"}, "type": "horizontal"})
    else:
        components.append(_layout_element(row[0], "1.2"))
    components.append({"style": {"weight": "0.50"}, "type": "space"})
    return {"components": components, "style": {"weight": "1.2"}, "type": "vertical"}


def _view_layout(rows: list[list[dict[str, Any]]], device_id: int) -> dict[str, Any]:
    """mkViewLayout port: the legacy ``$jason`` structure."""
    title = f"quickApp_device_{device_id}"
    items = [_layout_row(row) for row in rows]
    return {
        "$jason": {
            "body": {
                "header": {"style": {"height": "0"}, "title": title},
                "sections": {"items": items},
            },
            "head": {"title": title},
        }
    }


def _binding(event_type: str, name: str, value: str | None) -> list[dict[str, Any]]:
    """One uiView eventBinding (a device-action call into the QA)."""
    args: list[Any] = [event_type, name]
    if value is not None:
        args.append(value)
    return [
        {
            "params": {"actionName": "UIAction", "args": args},
            "type": "deviceAction",
        }
    ]


def _ui_view(rows: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """UI2NewUiView port: the new component format."""
    out: list[dict[str, Any]] = []
    for row in rows:
        weight = _UI_VIEW_WEIGHTS.get(len(row))
        components: list[dict[str, Any]] = []
        for el in row:
            typ, name = el["type"], el["id"]
            binding_value = (
                "$event.value" if typ in ("switch", "select", "multi", "slider") else None
            )
            event_binding: dict[str, Any] = {}
            if typ in ("button", "switch"):
                for event in ("onReleased", "onLongPressDown", "onLongPressReleased"):
                    event_binding[event] = _binding(event, name, binding_value)
            elif typ in ("select", "multi"):
                event_binding["onToggled"] = _binding("onToggled", name, binding_value)
            elif typ == "slider":
                event_binding["onChanged"] = _binding("onChanged", name, binding_value)
            component: dict[str, Any] = {
                "eventBinding": event_binding,
                "name": name,
                "style": {"weight": weight},
                "text": el["text"],
                "type": "select" if typ == "multi" else typ,
                "visible": True,
            }
            if typ == "slider":
                component["max"] = el["max"]
                component["min"] = el["min"]
                component["step"] = el["step"]
                component["value"] = el["value"]
            if typ in ("select", "multi"):
                component["options"] = list(el.get("options") or [])
                if typ == "select" and el.get("value"):  # "" value is omitted
                    component["value"] = el["value"]
                if typ == "multi":
                    component["values"] = list(el.get("values") or [])
                component["selectionType"] = "single" if typ == "select" else "multi"
            if typ == "switch":
                component["value"] = el["value"]
            components.append(component)
        out.append({"style": {"weight": "1.0"}, "type": "horizontal", "components": components})
    return out


# -- the inverse: HC3 UI structures -> --%%u rows ---------------------------------


def lua_literal(value: Any) -> str:
    """Serialize a JSON-compatible value as a Lua literal (the ``--%%u`` and
    ``--%%var`` value format)."""
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    if isinstance(value, list):
        return "{" + ",".join(lua_literal(item) for item in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join(f"{key}={lua_literal(val)}" for key, val in value.items()) + "}"
    return lua_literal(str(value))


def _callback_map(ui_callbacks: Any) -> dict[str, dict[str, str]]:
    """uiCallbacks ({name, eventType, callback} entries) ->
    {name: {eventType: callback}}."""
    callbacks: dict[str, dict[str, str]] = {}
    entries = ui_callbacks if isinstance(ui_callbacks, list) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        callback = entry.get("callback")
        if name and callback:
            callbacks.setdefault(str(name), {})[str(entry.get("eventType") or "")] = str(
                callback
            )
    return callbacks


def _element(component: dict[str, Any], callbacks: dict[str, dict[str, str]]) -> dict[str, Any]:
    """One UI component (uiView or legacy viewLayout shape) -> one --%%u
    element dict."""
    name = str(component.get("name") or "")
    text = str(component.get("text") or "")
    events = callbacks.get(name, {})
    typ = str(component.get("type") or "")
    if typ == "button":
        element: dict[str, Any] = {"button": name, "text": text}
        for event in ("onReleased", "onLongPressDown", "onLongPressReleased"):
            if events.get(event):
                element[event] = events[event]
    elif typ == "switch":
        element = {"switch": name, "text": text, "value": str(component.get("value", "false"))}
        if events.get("onReleased"):
            element["onReleased"] = events["onReleased"]
    elif typ == "slider":
        element = {
            "slider": name,
            "text": text,
            "min": str(component.get("min", "0")),
            "max": str(component.get("max", "100")),
            "step": str(component.get("step", "1")),
            "value": str(component.get("value", "0")),
        }
        if events.get("onChanged"):
            element["onChanged"] = events["onChanged"]
    elif typ == "select":
        multi = component.get("selectionType") == "multi"
        key = "multi" if multi else "select"
        options = [
            {
                "type": "option",
                "text": str(option.get("text", "")),
                "value": str(option.get("value", "")),
            }
            for option in (component.get("options") or [])
            if isinstance(option, dict)
        ]
        element = {key: name, "text": text, "options": options}
        if multi:
            element["values"] = [str(value) for value in (component.get("values") or [])]
        elif component.get("value"):
            element["value"] = str(component["value"])
        if events.get("onToggled"):
            element["onToggled"] = events["onToggled"]
    else:
        # unknown component kinds degrade to a label
        element = {"label": name, "text": text}
    return element


def _rows_from_view_layout(
    items: Any, callbacks: dict[str, dict[str, str]]
) -> list[list[dict[str, Any]]]:
    """The legacy $jason section items -> --%%u rows (one list of elements
    per vertical row, descending into horizontal containers)."""
    rows: list[list[dict[str, Any]]] = []

    def collect(component: dict[str, Any]) -> list[dict[str, Any]]:
        typ = str(component.get("type") or "")
        if typ in ("horizontal", "vertical"):
            elements: list[dict[str, Any]] = []
            for inner in component.get("components") or []:
                if isinstance(inner, dict):
                    elements.extend(collect(inner))
            return elements
        if typ == "space":
            return []
        return [_element(component, callbacks)]

    for item in items or []:
        if not isinstance(item, dict):
            continue
        elements = collect(item)
        if elements:
            rows.append(elements)
    return rows


def ui_to_u_rows(
    ui_view: Any = None, view_layout: Any = None, ui_callbacks: Any = None
) -> list[str]:
    """The inverse of compile_ui: translate the HC3's UI property structures
    back into ``--%%u`` row literals (uiView preferred, the legacy
    viewLayout as fallback; callback names come from uiCallbacks). Used when
    a QA is downloaded from the HC3 so its UI directives are regenerated."""
    callbacks = _callback_map(ui_callbacks)
    rows: list[list[dict[str, Any]]] = []
    if isinstance(ui_view, list) and ui_view:
        for row in ui_view:
            if not isinstance(row, dict):
                continue
            components = [
                component
                for component in (row.get("components") or [])
                if isinstance(component, dict)
            ]
            elements = [_element(component, callbacks) for component in components]
            if elements:
                rows.append(elements)
    elif isinstance(view_layout, dict):
        items = ((view_layout.get("$jason") or {}).get("body") or {}).get("sections") or {}
        rows = _rows_from_view_layout(items.get("items"), callbacks)
    return [lua_literal(row[0] if len(row) == 1 else row) for row in rows]
