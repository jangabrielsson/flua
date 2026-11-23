"""QuickApp UI: ``--%%u`` rows -> uiCallbacks + viewLayout + uiView.

Port of the QuickApp UI compiler
(extendUI/UI2uiCallbacks/mkViewLayout/UI2NewUiView). The row format: one
directive per row, one dict per element
(``{button="name", text=...}``, ``{slider=...}``, ``{label=...}``,
``{switch=...}``, ``{select=...}``, ``{multi=...}``,
``{tabView=...}``), or a list of element
dicts for several elements on one row. A tabView is full-width (alone on
its row): its tabs each hold rows in the same shapes.

The two output structures match the HC3's device properties:

- ``viewLayout`` — the legacy ``$jason`` format.
- ``uiView`` — the newer component format (rows of ``horizontal`` rows with
  typed components and device-action event bindings).
- ``uiCallbacks`` — {name, eventType, callback} entries so the HC3 (and
  flua's QuickApp runtime) can route UI events to QA methods.

``useUiView`` (device property) picks which of the two the UI renders; flua
defaults it to false (the legacy layout is still the common case),
``--%%useUiView:true`` selects the new format.
"""

# Lua identifiers (bare table keys) and reserved words — other keys emit in
# the bracket form ['$jason']=... so lua_literal output is always valid Lua.
import re
from typing import Any

_LUA_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LUA_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for",
    "function", "goto", "if", "in", "local", "nil", "not", "or",
    "repeat", "return", "then", "true", "until", "while",
}

# Per-element weight by row size in the uiView format (the exact table).
_UI_VIEW_WEIGHTS = {1: "1.0", 2: "0.5", 3: "0.25", 4: "0.33", 5: "0.20"}

_ELEMENT_KEYS = (
    "button",
    "slider",
    "label",
    "select",
    "switch",
    "multi",
    "tabView",
    "image",
    "collapsible",
)


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
        if len(row) > 1 and any(k in el for el in row for k in ("tabView", "collapsible")):
            raise ValueError(
                "a tabView/collapsible must sit alone on its --%%u row (it is full-width)"
            )
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
                el.setdefault("onToggleOn", "")  # the 5.221 split toggle events
                el.setdefault("onToggleOff", "")
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
            elif typ == "tabView":
                # a tabView holds named tabs, each with its own rows
                # (a list of rows in the same shape as the top-level
                # directives — so elements inside tabs normalize the same)
                el.setdefault("onTabChanged", "")
                el.setdefault("visible", True)
                tabs: list[dict[str, Any]] = []
                for raw_tab in el.get("tabs") or []:
                    tab = dict(raw_tab)
                    tab.setdefault("name", "")
                    tab.setdefault("text", "")
                    tab_rows: list[list[dict[str, Any]]] = []
                    for raw_row in tab.get("components") or []:
                        if isinstance(raw_row, list):
                            tab_rows.append([dict(e) for e in raw_row])
                        else:
                            tab_rows.append([dict(raw_row)])
                    tab["rows"] = tab_rows
                    tabs.append(tab)
                el["tabs"] = tabs
                el.setdefault("activeTab", tabs[0]["name"] if tabs else "")
                el["weight"] = "1.0"
            elif typ == "image":
                el.setdefault("url", "")
                el.setdefault("visible", True)
            elif typ == "collapsible":
                # a collapsible section holds rows exactly like a tab does
                el.setdefault("collapsed", False)
                el.setdefault("disabled", False)
                el.setdefault("visible", True)
                el.setdefault("text", "")
                body_rows: list[list[dict[str, Any]]] = []
                for raw_row in el.get("components") or []:
                    if isinstance(raw_row, list):
                        body_rows.append([dict(e) for e in raw_row])
                    else:
                        body_rows.append([dict(raw_row)])
                el["rows"] = body_rows
                el["weight"] = "1.0"
    # elements inside tabs and collapsibles normalize exactly like
    # top-level ones
    for row in rows:
        for el in row:
            if el["type"] == "tabView":
                for tab in el["tabs"]:
                    _apply_defaults(tab["rows"])
            elif el["type"] == "collapsible":
                _apply_defaults(el["rows"])


def _callbacks(rows: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """UI2uiCallbacks port: {name, eventType, callback} entries.
    Descends into tabView tabs — elements nested there route UI events
    through uiCallbacks exactly like top-level ones."""
    callbacks: list[dict[str, Any]] = []
    for row in rows:
        for el in row:
            typ, name = el["type"], el["id"]
            if typ in ("button", "switch"):
                events = ("onReleased", "onLongPressDown", "onLongPressReleased")
                if typ == "switch":
                    events = (*events, "onToggleOn", "onToggleOff")
                for event in events:
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
            elif typ == "tabView":
                callbacks.append(
                    {
                        "callback": el.get("onTabChanged", ""),
                        "eventType": "onTabChanged",
                        "name": name,
                    }
                )
                for tab in el["tabs"]:
                    callbacks.extend(_callbacks(tab["rows"]))
            elif typ == "collapsible":
                # no events of its own: elements inside it route like
                # top-level ones
                callbacks.extend(_callbacks(el["rows"]))
    return callbacks


def _options(el: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(option, type="option") for option in el.get("options") or []]


def _layout_element(el: dict[str, Any], weight: str) -> dict[str, Any]:
    """ELMS port: one legacy viewLayout component."""
    typ, name = el["type"], el["id"]
    style_weight = el.get("weight") or weight or "0.50"
    if typ == "button":
        # NOTE: deliberately no event fields — the HC3's own legacy exports
        # carry none (the event -> method binding lives in uiCallbacks only).
        # Declaring onReleased etc. on the element makes the HC3's import
        # re-derive uiCallbacks with generated default names (ui<b2>OnReleased)
        # and drop the custom handlers.
        return {
            "name": name,
            "visible": el.get("visible", True),
            "style": {"weight": style_weight},
            "text": el["text"],
            "type": "button",
        }
    if typ in ("select", "multi"):
        # legacy format: the selection lives in "values" (an array), even
        # for single select — its declared initial value is el["value"]
        # (the multi-select convention uses el["values"])
        if typ == "select" and el.get("value") is not None:
            values = [el["value"]]
        else:
            values = list(el.get("values") or [])
        element = {
            "name": name,
            "style": {"weight": style_weight},
            "text": el["text"],
            "type": "select",
            "visible": el.get("visible", True),
            "selectionType": "single" if typ == "select" else "multi",
            "options": _options(el),
            "values": values,
        }
        return element
    if typ == "switch":
        # no event fields (see the button comment)
        return {
            "name": name,
            "visible": el.get("visible", True),
            "style": {"weight": style_weight},
            "text": el["text"],
            "type": "switch",
            "value": el["value"],
        }
    if typ == "slider":
        element = {
            "name": name,
            "visible": el.get("visible", True),
            "step": el["step"],
            "value": el["value"],
            "max": el["max"],
            "min": el["min"],
            "style": {"weight": style_weight},
            "text": el["text"],
            "type": "slider",
        }
        if el.get("unit"):
            element["unit"] = el["unit"]
        return element
    if typ == "image":
        # the HC3's own legacy views carry image elements (russound's
        # album art in json/view.json): url + useProxy, no events
        element = {
            "name": name,
            "visible": el.get("visible", True),
            "url": el["url"],
            "style": {"weight": style_weight},
            "type": "image",
        }
        if el.get("useProxy"):
            element["useProxy"] = True
        if el.get("classes"):
            element["classes"] = list(el["classes"])
        return element
    # label
    return {
        "name": name,
        "visible": el.get("visible", True),
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


def _layout_tabview(el: dict[str, Any]) -> dict[str, Any]:
    """One legacy viewLayout tabView item: the shape the HC3's own
    $jason views use (sonosGroup's v2 view nests a tabView in the body),
    minus event fields — the legacy convention keeps the event->method
    binding in uiCallbacks only (see the button comment in _layout_element)."""
    return {
        "type": "tabView",
        "name": el["id"],
        "activeTab": el["activeTab"],
        "visible": el.get("visible", True),
        "style": {"weight": "1"},
        "tabs": [
            {
                "type": "tab",
                "name": tab["name"],
                "text": tab["text"],
                "components": [_layout_row(row) for row in tab["rows"]],
            }
            for tab in el["tabs"]
        ],
    }


def _layout_collapsible(el: dict[str, Any]) -> dict[str, Any]:
    """One legacy viewLayout collapsible item (the sonosGroup v2 shape,
    minus event fields — the legacy convention, see _layout_element)."""
    return {
        "type": "collapsible",
        "name": el["id"],
        "text": el["text"],
        "collapsed": el["collapsed"],
        "disabled": el["disabled"],
        "visible": el.get("visible", True),
        "style": {"weight": "1"},
        "components": [_layout_row(row) for row in el["rows"]],
    }


def _view_layout(rows: list[list[dict[str, Any]]], device_id: int) -> dict[str, Any]:
    """mkViewLayout port: the legacy ``$jason`` structure."""
    title = f"quickApp_device_{device_id}"

    def _item(row: list[dict[str, Any]]) -> dict[str, Any]:
        if len(row) == 1:
            if row[0]["type"] == "tabView":
                return _layout_tabview(row[0])
            if row[0]["type"] == "collapsible":
                return _layout_collapsible(row[0])
        return _layout_row(row)

    items = [_item(row) for row in rows]
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


def _ui_view_component(el: dict[str, Any], weight: str) -> dict[str, Any]:
    """One uiView component for a non-tabView element."""
    typ, name = el["type"], el["id"]
    binding_value = "$event.value" if typ in ("switch", "select", "multi", "slider") else None
    event_binding: dict[str, Any] = {}
    if typ in ("button", "switch"):
        for event in ("onReleased", "onLongPressDown", "onLongPressReleased"):
            event_binding[event] = _binding(event, name, binding_value)
        if typ == "switch":
            event_binding["onToggleOn"] = _binding("onToggleOn", name, "$event.value")
            event_binding["onToggleOff"] = _binding("onToggleOff", name, "$event.value")
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
        "visible": el.get("visible", True),
    }
    if typ == "slider":
        component["max"] = el["max"]
        component["min"] = el["min"]
        component["step"] = el["step"]
        component["value"] = el["value"]
    if typ in ("select", "multi"):
        component["options"] = list(el.get("options") or [])
        # the 5.221 schema: the current selection lives in `values`
        # (an array) for BOTH modes — a single select carries its
        # one value in it
        if typ == "select" and el.get("value"):
            component["values"] = [el["value"]]
        if typ == "multi":
            component["values"] = list(el.get("values") or [])
        component["selectionType"] = "single" if typ == "select" else "multi"
    if typ == "switch":
        component["value"] = el["value"]
    if typ == "image":
        component["url"] = el["url"]
        if el.get("useProxy"):
            component["useProxy"] = True
        if el.get("classes"):
            component["classes"] = list(el["classes"])
    # the 5.221 element properties the viewer renders: named icons,
    # switch hints, disabled state, slider units
    for key in ("image", "hint", "disabled"):
        if el.get(key) is not None:
            component[key] = el[key]
    if typ == "slider" and el.get("unit"):
        component["unit"] = el["unit"]
    return component


def _ui_view_row(row: list[dict[str, Any]]) -> dict[str, Any]:
    """One uiView row: a horizontal container of components."""
    weight = _UI_VIEW_WEIGHTS.get(len(row))
    return {
        "style": {"weight": "1.0"},
        "type": "horizontal",
        "components": [_ui_view_component(el, weight) for el in row],
    }


def _ui_view_tabview(el: dict[str, Any]) -> dict[str, Any]:
    """One uiView tabView component: the shape the HC3's own views use
    (ui-views/types/com.fibaro.colorController.json) — named tabs, each
    holding uiView rows, with onTabChanged bound like the other events.
    The style weights mirror the HC3's tabbed views (the tabView and each
    tab carry style.weight there)."""
    return {
        "type": "tabView",
        "name": el["id"],
        "activeTab": el["activeTab"],
        "visible": el.get("visible", True),
        "style": {"weight": "1"},
        "eventBinding": {"onTabChanged": _binding("onTabChanged", el["id"], "$event.value")},
        "tabs": [
            {
                "type": "tab",
                "name": tab["name"],
                "text": tab["text"],
                "style": {"weight": "1"},
                "components": [_ui_view_row(row) for row in tab["rows"]],
            }
            for tab in el["tabs"]
        ],
    }


def _ui_view_collapsible(el: dict[str, Any]) -> dict[str, Any]:
    """One uiView collapsible component: a named section holding uiView
    rows (the sonosGroup v2 shape — collapsed/disabled toggles the body)."""
    return {
        "type": "collapsible",
        "name": el["id"],
        "text": el["text"],
        "collapsed": el["collapsed"],
        "disabled": el["disabled"],
        "visible": el.get("visible", True),
        "style": {"weight": "1"},
        "components": [_ui_view_row(row) for row in el["rows"]],
    }


def _ui_view(rows: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """UI2NewUiView port: the new component format."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if len(row) == 1 and row[0]["type"] in ("tabView", "collapsible"):
            # full-width elements: alone on their row (the compile raises
            # otherwise) — still wrapped in a row so every uiView entry
            # keeps the uniform row shape (the viewer and the inverse both
            # iterate row.components)
            builder = _ui_view_tabview if row[0]["type"] == "tabView" else _ui_view_collapsible
            out.append(
                {
                    "style": {"weight": "1.0"},
                    "type": "horizontal",
                    "components": [builder(row[0])],
                }
            )
        else:
            out.append(_ui_view_row(row))
    return out


# -- the inverse: HC3 UI structures -> --%%u rows ---------------------------------


def lua_literal(value: Any) -> str:
    """Serialize a JSON-compatible value as a Lua literal (the ``--%%u`` and
    ``--%%var`` value format). Non-identifier table keys (like ``$jason``)
    emit in the bracket form so the output is valid Lua."""
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
        return "{" + ",".join(
            f"{key}={lua_literal(val)}"
            if _LUA_IDENT_RE.fullmatch(key) and key not in _LUA_KEYWORDS
            else f"[{lua_literal(key)}]={lua_literal(val)}"
            for key, val in value.items()
        ) + "}"
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
            callbacks.setdefault(str(name), {})[str(entry.get("eventType") or "")] = str(callback)
    return callbacks


def _element(component: dict[str, Any], callbacks: dict[str, dict[str, str]]) -> dict[str, Any]:
    """One UI component (uiView or legacy viewLayout shape) -> one --%%u
    element dict. Event targets come from the component's own event fields
    when present (the HC3's canonical form for legacy viewLayout elements),
    falling back to the uiCallbacks mirror (the uiView's only form)."""
    name = str(component.get("name") or "")
    text = str(component.get("text") or "")
    events = callbacks.get(name, {})

    def event_target(event: str) -> str:
        declared = component.get(event)
        return str(declared) if declared else events.get(event, "")

    typ = str(component.get("type") or "")
    if typ == "button":
        element: dict[str, Any] = {"button": name, "text": text}
        for event in ("onReleased", "onLongPressDown", "onLongPressReleased"):
            target = event_target(event)
            if target:
                element[event] = target
    elif typ == "switch":
        element = {"switch": name, "text": text, "value": str(component.get("value", "false"))}
        for event in ("onReleased", "onToggleOn", "onToggleOff"):
            target = event_target(event)
            if target:
                element[event] = target
    elif typ == "slider":
        element = {
            "slider": name,
            "text": text,
            "min": str(component.get("min", "0")),
            "max": str(component.get("max", "100")),
            "step": str(component.get("step", "1")),
            "value": str(component.get("value", "0")),
        }
        if component.get("unit"):
            element["unit"] = str(component["unit"])
        if event_target("onChanged"):
            element["onChanged"] = event_target("onChanged")
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
        # the selection comes back too: the 5.221 schema carries it in
        # "values" (single select's first entry)
        if multi:
            if isinstance(component.get("values"), list):
                element["values"] = list(component["values"])
        elif component.get("value") is not None:
            element["value"] = component["value"]
        elif isinstance(component.get("values"), list) and component["values"]:
            element["value"] = component["values"][0]
        if event_target("onToggled"):
            element["onToggled"] = event_target("onToggled")
    elif typ == "image":
        element = {"image": name, "url": str(component.get("url") or "")}
        if component.get("useProxy") is True:
            element["useProxy"] = True
        if isinstance(component.get("classes"), list):
            element["classes"] = list(component["classes"])
    elif typ == "collapsible":
        # the body comes back as rows re-mapped through _element
        body_rows: list[list[dict[str, Any]]] = []
        for row in component.get("components") or []:
            if not isinstance(row, dict):
                continue
            elements = [
                _element(inner, callbacks)
                for inner in row.get("components") or []
                if isinstance(inner, dict)
            ]
            if elements:
                body_rows.append(elements)
        element = {
            "collapsible": name,
            "text": text,
            "collapsed": component.get("collapsed") is True,
            "disabled": component.get("disabled") is True,
            "components": body_rows,
        }
    elif typ == "tabView":
        # tabs come back with their rows re-mapped through _element (a tab's
        # components are uiView/legacy rows, not flat elements)
        tabs: list[dict[str, Any]] = []
        for tab in component.get("tabs") or []:
            if not isinstance(tab, dict):
                continue
            tab_rows: list[list[dict[str, Any]]] = []
            for row in tab.get("components") or []:
                if not isinstance(row, dict):
                    continue
                elements = [
                    _element(inner, callbacks)
                    for inner in row.get("components") or []
                    if isinstance(inner, dict)
                ]
                if elements:
                    tab_rows.append(elements)
            tabs.append(
                {
                    "name": str(tab.get("name") or ""),
                    "text": str(tab.get("text") or ""),
                    "components": tab_rows,
                }
            )
        element = {
            "tabView": name,
            "activeTab": str(component.get("activeTab") or ""),
            "tabs": tabs,
        }
        if event_target("onTabChanged"):
            element["onTabChanged"] = event_target("onTabChanged")
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
