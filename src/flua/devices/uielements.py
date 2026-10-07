"""Default ("embedded") UI elements for common QA device types.

The real HC3 renders these automatically per device type — a binarySwitch
gets Turn On/Turn Off buttons and a colored state label even when the QA
defines no ``--%%u`` UI of its own. flua does the same, viewer-side: the
viewer fetches ``GET /flua/embeddedUI`` and prepends the type's default rows
to the QA's custom ``uiView``.

The tables are the PLua Emu.lib definitions (``devices/uielements.lua``),
translated to Python and kept table-driven so developers can add their own
types in one place.

Deliberately NOT part of the device's ``viewLayout``/``uiView`` properties:
the HC3 adds these elements itself, so they must never leak into the
``/devices`` structure or the .fqa export.

- ``EMBEDDED_UI`` — ``type -> rows``; each row is a list of components in
  the same shape the viewer renders for ``uiView`` (type/name/text/...),
  except interactive controls carry ``action`` (a device action invoked via
  ``POST /devices/{id}/action/{action}``, like the HC3 client) instead of an
  ``eventBinding``.
- ``EMBEDDED_WATCHES`` — ``type -> rules``; each rule maps a device property
  to a live component update: ``{property, id, prop ("text"|"value"),
  fmt}``. ``fmt`` is a ``%``-format string (numbers) or a callable.

Element ids use the HC3 convention: the ``__`` prefix marks embedded
(default-view) ids, so they can never collide with the QA's own ids.
"""

from __future__ import annotations

from typing import Any

BIN_FALSE = "<center><font color='red'>FALSE</font></center>"
BIN_TRUE = "<center><font color='green'>TRUE</font></center>"


def _custom_bin(value: Any) -> str:
    return BIN_TRUE if value else BIN_FALSE


def _int_value(value: Any) -> str:
    """A dimmer's value as an integer — the HC3 UI shows no decimals."""
    return str(int(float(value) + 0.5))


def _color_value(value: Any) -> str:
    """The colorController's state label: colored ON/OFF from the value table."""
    if not isinstance(value, dict):
        return BIN_FALSE
    dimming = value.get("dimming") or {}
    brightness = dimming.get("brightness") or 0
    level = int(float(brightness) + 0.5)  # PLua: math.floor(brightness + 0.5)
    color = value.get("color") or {}
    return "<font color='rgb({},{},{})'>{}</font>".format(
        color.get("r") or 0,
        color.get("g") or 0,
        color.get("b") or 0,
        "ON" if level else "OFF",
    )


EMBEDDED_UI: dict[str, list[list[dict[str, Any]]]] = {
    "com.fibaro.binarySwitch": [
        [{"type": "label", "name": "__binarysensorValue", "text": BIN_FALSE}],
        [
            {"type": "button", "name": "__turnOn", "text": "Turn On", "action": "turnOn"},
            {"type": "button", "name": "__turnOff", "text": "Turn Off", "action": "turnOff"},
        ],
    ],
    "com.fibaro.multilevelSwitch": [
        [{"type": "label", "name": "__multiswitchValue", "text": "0"}],
        [
            {"type": "button", "name": "__turnOn", "text": "Turn On", "action": "turnOn"},
            {"type": "button", "name": "__turnOff", "text": "Turn Off", "action": "turnOff"},
        ],
        [{"type": "slider", "name": "__setValue", "text": "", "action": "setValue"}],
    ],
    "com.fibaro.colorController": [
        [{"type": "label", "name": "__colorComponentValue", "text": "white"}],
        [
            {"type": "button", "name": "__turnOn", "text": "Turn On", "action": "turnOn"},
            {"type": "button", "name": "__turnOff", "text": "Turn Off", "action": "turnOff"},
        ],
        [{"type": "slider", "name": "__setValue", "text": "", "action": "setValue"}],
        [
            {
                "type": "slider",
                "name": "__setColorComponentR",
                "text": "",
                "max": 255,
                "action": "setValue",
            },
            {
                "type": "slider",
                "name": "__setColorComponentG",
                "text": "",
                "max": 255,
                "action": "setValue",
            },
            {
                "type": "slider",
                "name": "__setColorComponentB",
                "text": "",
                "max": 255,
                "action": "setValue",
            },
            {
                "type": "slider",
                "name": "__setColorComponentW",
                "text": "",
                "max": 255,
                "action": "setValue",
            },
        ],
    ],
    "com.fibaro.multilevelSensor": [
        [{"type": "label", "name": "__multisensorValue", "text": "0"}],
    ],
    "com.fibaro.binarySensor": [
        [{"type": "label", "name": "__binarysensorValue", "text": BIN_FALSE}],
    ],
    "com.fibaro.doorSensor": [
        [{"type": "label", "name": "__doorSensor", "text": BIN_FALSE}],
    ],
    "com.fibaro.windowSensor": [
        [{"type": "label", "name": "__windowSensor", "text": BIN_FALSE}],
    ],
    "com.fibaro.temperatureSensor": [
        [{"type": "label", "name": "__temperatureSensor", "text": "0"}],
    ],
    "com.fibaro.humiditySensor": [
        [{"type": "label", "name": "__humiditySensor", "text": "0"}],
    ],
}

EMBEDDED_WATCHES: dict[str, list[dict[str, Any]]] = {
    "com.fibaro.binarySwitch": [
        {"property": "value", "id": "__binarysensorValue", "prop": "text", "fmt": _custom_bin},
    ],
    "com.fibaro.binarySensor": [
        # added over the PLua table: the HC3 shows the state on binary
        # sensors too (same as door/window sensors)
        {"property": "value", "id": "__binarysensorValue", "prop": "text", "fmt": _custom_bin},
    ],
    "com.fibaro.multilevelSwitch": [
        {"property": "value", "id": "__setValue", "prop": "value", "fmt": _int_value},
        {"property": "value", "id": "__multiswitchValue", "prop": "text", "fmt": _int_value},
    ],
    "com.fibaro.colorController": [
        {"property": "value", "id": "__colorComponentValue", "prop": "text", "fmt": _color_value},
    ],
    "com.fibaro.multilevelSensor": [
        {"property": "value", "id": "__multisensorValue", "prop": "text", "fmt": "%.3f"},
    ],
    "com.fibaro.doorSensor": [
        {"property": "value", "id": "__doorSensor", "prop": "text", "fmt": _custom_bin},
    ],
    "com.fibaro.windowSensor": [
        {"property": "value", "id": "__windowSensor", "prop": "text", "fmt": _custom_bin},
    ],
    "com.fibaro.temperatureSensor": [
        {"property": "value", "id": "__temperatureSensor", "prop": "text", "fmt": "%.2f°"},
    ],
    "com.fibaro.humiditySensor": [
        {"property": "value", "id": "__humiditySensor", "prop": "text", "fmt": "%.2f%%"},
    ],
}


def embedded_view(device: dict[str, Any]) -> dict[str, Any] | None:
    """The device's default view: static rows + live values, or None.

    Live values come from the watched device properties, resolved on every
    call (the viewer polls each tick). Missing properties leave the static
    default text in place.
    """
    device_type = device.get("type")
    rows = EMBEDDED_UI.get(device_type)
    if rows is None:
        return None
    properties = device.get("properties") or {}
    values: dict[str, dict[str, Any]] = {}
    for rule in EMBEDDED_WATCHES.get(device_type) or ():
        raw = properties.get(rule["property"])
        if raw is None:
            continue
        fmt = rule["fmt"]
        if callable(fmt):
            value: Any = fmt(raw)
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            if "%" not in fmt:
                value = fmt
            else:
                try:
                    value = fmt % raw
                except (TypeError, ValueError):
                    continue
        else:
            continue
        values.setdefault(rule["id"], {})[rule["prop"]] = value
    # rows in the uiView shape the viewer renders (a compact list per row in
    # the table above; wrapped into horizontal rows here)
    ui_view = [
        {"style": {"weight": "1.0"}, "type": "horizontal", "components": row} for row in rows
    ]
    return {"type": device_type, "uiView": ui_view, "values": values}
