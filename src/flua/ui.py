"""QuickApp UI: ``--%%u`` rows -> uiCallbacks + viewLayout + uiView.

Faithful Python port of plua's ``src/lua/fibaro/ui.lua``
(extendUI/UI2uiCallbacks/mkViewLayout/UI2NewUiView). The row format is the
same plua one: one directive per row, one dict per element
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

# Per-element weight by row size in the uiView format (plua's exact table).
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
            width = width[:-3]  # plua: strip a trailing ".00"
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
                if typ == "select" and el.get("value"):  # plua: "" value is omitted
                    component["value"] = el["value"]
                if typ == "multi":
                    component["values"] = list(el.get("values") or [])
                component["selectionType"] = "single" if typ == "select" else "multi"
            if typ == "switch":
                component["value"] = el["value"]
            components.append(component)
        out.append({"style": {"weight": "1.0"}, "type": "horizontal", "components": components})
    return out
