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
  ``eventBinding``. A button may also carry a fixed ``value``: it rides
  along as the action's single argument (the player's mute/unmute pass
  0/1 to setMute). A slider may carry ``argKey``: the viewer sends
  ``args: [{<argKey>: <value>}]`` instead of a bare scalar — the
  colorController's red/green/blue/warmWhite sliders drive
  setColorComponents this way, matching the HC3 client's onAction shape.
  A slider may instead carry ``calls``: a list of ``{action, offset}`` —
  one drag fires each action with the slider value plus its offset (the
  hvacSystemAuto's auto-mode slider moves both setpoints: target ±
  hysteresis). ``disabled`` disables a control (the hvacSystemAuto's
  setpoint controls in Off mode). A type entry may also be a *callable*
  taking the device properties and returning the rows — the
  hvac thermostat family's rows depend on the current mode/setpoints and
  are re-resolved on every poll.
- ``EMBEDDED_WATCHES`` — ``type -> rules``; each rule maps a device property
  to a live component update: ``{property, id, prop ("text"|"value"),
  fmt}``. ``fmt`` is a ``%``-format string (numbers) or a callable.

Element ids use the HC3 convention: the ``__`` prefix marks embedded
(default-view) ids, so they can never collide with the QA's own ids.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

BIN_FALSE = "<center><font color='red'>FALSE</font></center>"
BIN_TRUE = "<center><font color='green'>TRUE</font></center>"


def _shutter_row() -> list[dict[str, str]]:
    """The shutter family's default row: glyph buttons for up / stop / down.
    A factory so every type entry gets its own fresh row (no shared state)."""
    return [
        {"type": "button", "name": "__open", "text": "▲", "action": "open"},
        {"type": "button", "name": "__stop", "text": "■", "action": "stop"},
        {"type": "button", "name": "__close", "text": "▼", "action": "close"},
    ]


def _position_slider_row() -> list[dict[str, str]]:
    """The positioned shutter family's position row: a slider over the
    device's ``value`` (0-99, per the QA_types_ui RollerShutter example)."""
    return [{"type": "slider", "name": "__setValue", "text": "", "action": "setValue"}]


def _custom_bin(value: Any, properties: dict[str, Any] | None = None) -> str:
    return BIN_TRUE if value else BIN_FALSE


def _int_value(value: Any, properties: dict[str, Any] | None = None) -> str:
    """A dimmer's value as an integer — the HC3 UI shows no decimals."""
    return str(int(float(value) + 0.5))


def _strip_zeros(text: str) -> str:
    """Drop insignificant trailing zeros (and the separator once bare):
    50.000 -> 50, 348.400 -> 348.4 — the HC3's compact panel style."""
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _multisensor_value(value: Any, properties: dict[str, Any] | None = None) -> str:
    """A multilevelSensor's value with its unit string appended (the HC3
    carries the unit as a separate ``unit`` property)."""
    try:
        text = _strip_zeros(f"{value:.3f}")
    except (TypeError, ValueError):
        text = str(value)
    unit = (properties or {}).get("unit")
    if unit:
        text = f"{text}{unit}"
    return text


def _temp_value(value: Any, properties: dict[str, Any] | None = None) -> str:
    try:
        text = _strip_zeros(f"{value:.2f}")
    except (TypeError, ValueError):
        text = str(value)
    return text + "°"


def _humidity_value(value: Any, properties: dict[str, Any] | None = None) -> str:
    try:
        text = _strip_zeros(f"{value:.2f}")
    except (TypeError, ValueError):
        text = str(value)
    return text + "%"


def _color_value(value: Any, properties: dict[str, Any] | None = None) -> str:
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


def _num(value: Any, default: float = 0.0) -> float:
    """A numeric device property — tolerant of the ``{value, unit}`` object
    shape some QAs store for setpoints, and of missing/None values."""
    if isinstance(value, dict):
        value = value.get("value", default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _step(steps: Any, unit: str, default: float = 0.5) -> float:
    """A setpointStep dict resolved for the device's unit
    (``{"C": 0.5, "F": 1}``), or a plain numeric step."""
    if isinstance(steps, dict):
        try:
            return float(steps.get(unit, default))
        except (TypeError, ValueError):
            return default
    return _num(steps, default) or default


def _hvac_mode(properties: dict[str, Any], modes: tuple[str, ...], default: str) -> str:
    mode = properties.get("thermostatMode")
    return mode if mode in modes else default


def _hvac_target(properties: dict[str, Any], modes: tuple[str, ...], default: str) -> float:
    """The displayed setpoint: the deadband center (heat/cool average) in
    Auto mode, else the active side's setpoint."""
    mode = _hvac_mode(properties, modes, default)
    heat = _num(properties.get("heatingThermostatSetpoint"))
    cool = _num(properties.get("coolingThermostatSetpoint"))
    if mode == "Auto":
        return (heat + cool) / 2
    if mode == "Cool":
        return cool
    return heat


def _hvac_format(target: float, properties: dict[str, Any]) -> str:
    """The target formatted like the HC3's compact panel: 21.5°C."""
    text = _strip_zeros(f"{target:.2f}") + "°"
    unit = properties.get("unit")
    return text + unit if unit else text


def _hvac_target_text(
    value: Any,
    properties: dict[str, Any] | None = None,
    modes: tuple[str, ...] = ("Auto", "Off", "Heat", "Cool"),
    default: str = "Heat",
) -> str:
    """EMBEDDED_WATCHES fmt: the hvac thermostat's displayed setpoint label.
    "--" when the thermostat is Off (no setpoint is active)."""
    props = properties or {}
    if _hvac_mode(props, modes, default) == "Off":
        return "--"
    return _hvac_format(_hvac_target(props, modes, default), props)


def _hvac_target_value(
    value: Any,
    properties: dict[str, Any] | None = None,
    modes: tuple[str, ...] = ("Auto", "Off", "Heat", "Cool"),
    default: str = "Heat",
) -> str:
    """EMBEDDED_WATCHES fmt: the same target as a plain number string — the
    setpoint slider's live position ("" when Off: the slider is disabled)."""
    props = properties or {}
    if _hvac_mode(props, modes, default) == "Off":
        return ""
    return _strip_zeros(f"{_hvac_target(props, modes, default):.2f}")


def _hvac_rows(
    properties: dict[str, Any],
    modes: tuple[str, ...] = ("Auto", "Off", "Heat", "Cool"),
) -> list[list[dict[str, Any]]]:
    """The hvac thermostat family's default view, resolved from the device's
    current properties on every poll: the setpoint steppers + target label,
    the setpoint slider, and the mode buttons (two per row, in ``modes``
    order — the Cool/Heat types pass their single-side mode set).

    - Auto: minus lowers the heating setpoint and plus raises the cooling
      setpoint by ``hysteresis`` (the deadband halves); the slider moves
      BOTH setpoints around the target (the displayed average) and its range
      is inset by hysteresis so each side stays within the capabilities.
    - Heat/Cool: steppers and slider drive the active side's setpoint over
      the capability range, stepping by its setpointStep for the unit.
    - Off: the setpoint controls are disabled.

    A mode the type does not support resolves to its default (Heat, or the
    first non-Off mode of the set — Cool for the cool-only type).
    """
    default = "Heat" if "Heat" in modes else next(m for m in modes if m != "Off")
    mode = _hvac_mode(properties, modes, default)
    heat = _num(properties.get("heatingThermostatSetpoint"))
    cool = _num(properties.get("coolingThermostatSetpoint"))
    hyst = _num(properties.get("hysteresis"), 1.0) or 1.0
    unit = properties.get("unit") or ""
    heat_step = _step(properties.get("heatingThermostatSetpointStep"), unit)
    cool_step = _step(properties.get("coolingThermostatSetpointStep"), unit)
    heat_min = _num(properties.get("heatingThermostatSetpointCapabilitiesMin"), 4.0)
    heat_max = _num(properties.get("heatingThermostatSetpointCapabilitiesMax"), 30.0)
    cool_min = _num(properties.get("coolingThermostatSetpointCapabilitiesMin"), 4.0)
    cool_max = _num(properties.get("coolingThermostatSetpointCapabilitiesMax"), 30.0)
    off = mode == "Off"

    minus: dict[str, Any] = {"type": "button", "name": "__hvacMinus", "text": "−"}
    plus: dict[str, Any] = {"type": "button", "name": "__hvacPlus", "text": "+"}
    slider: dict[str, Any] = {"type": "slider", "name": "__hvacSetpoint", "text": ""}
    if mode == "Auto":
        minus.update(
            action="setHeatingThermostatSetpoint",
            value=round(max(heat_min, heat - hyst), 2),
        )
        plus.update(
            action="setCoolingThermostatSetpoint",
            value=round(min(cool_max, cool + hyst), 2),
        )
        slider.update(
            min=round(max(heat_min, cool_min) + hyst, 2),
            max=round(min(heat_max, cool_max) - hyst, 2),
            step=round(min(heat_step, cool_step), 2),
            # one drag moves the whole deadband: target ± hysteresis
            calls=[
                {"action": "setHeatingThermostatSetpoint", "offset": round(-hyst, 2)},
                {"action": "setCoolingThermostatSetpoint", "offset": round(hyst, 2)},
            ],
        )
    elif mode == "Cool":
        minus.update(
            action="setCoolingThermostatSetpoint",
            value=round(max(cool_min, cool - cool_step), 2),
        )
        plus.update(
            action="setCoolingThermostatSetpoint",
            value=round(min(cool_max, cool + cool_step), 2),
        )
        slider.update(
            min=round(cool_min, 2),
            max=round(cool_max, 2),
            step=round(cool_step, 2),
            action="setCoolingThermostatSetpoint",
        )
    else:  # Heat (and the Off state's controls, disabled below)
        minus.update(
            action="setHeatingThermostatSetpoint",
            value=round(max(heat_min, heat - heat_step), 2),
        )
        plus.update(
            action="setHeatingThermostatSetpoint",
            value=round(min(heat_max, heat + heat_step), 2),
        )
        slider.update(
            min=round(heat_min, 2),
            max=round(heat_max, 2),
            step=round(heat_step, 2),
            action="setHeatingThermostatSetpoint",
        )
    if off:
        minus["disabled"] = True
        plus["disabled"] = True
        slider["disabled"] = True
    return [
        [
            minus,
            {
                "type": "label",
                "name": "__hvacSetpointValue",
                "text": _hvac_target_text("", properties, modes, default),
            },
            plus,
        ],
        [slider],
        *[
            [
                {
                    "type": "button",
                    "name": f"__mode{m}",
                    "text": m,
                    "action": "setThermostatMode",
                    "value": m,
                }
                for m in modes[index : index + 2]
            ]
            for index in range(0, len(modes), 2)
        ],
    ]


EMBEDDED_UI: dict[
    str,
    list[list[dict[str, Any]]] | Callable[[dict[str, Any]], list[list[dict[str, Any]]]],
] = {
    "com.fibaro.hvacSystemAuto": _hvac_rows,
    # the single-side variants: same panel, only their mode set differs
    "com.fibaro.hvacSystemCool": partial(_hvac_rows, modes=("Off", "Cool")),
    "com.fibaro.hvacSystemHeat": partial(_hvac_rows, modes=("Off", "Heat")),
    "com.fibaro.binarySwitch": [
        [{"type": "label", "name": "__binarysensorValue", "text": BIN_FALSE}],
        [
            {"type": "button", "name": "__turnOn", "text": "Turn On", "action": "turnOn"},
            {"type": "button", "name": "__turnOff", "text": "Turn Off", "action": "turnOff"},
        ],
    ],
    "com.fibaro.baseShutter": [_shutter_row()],
    "com.fibaro.rollerShutter": [_shutter_row(), _position_slider_row()],
    "com.fibaro.remoteBaseShutter": [_shutter_row()],
    "com.fibaro.remoteRollerShutter": [_shutter_row(), _position_slider_row()],
    "com.fibaro.player": [
        # media transport: previous / pause / play / stop / next
        [
            {"type": "button", "name": "__prev", "text": "⏮", "action": "prev"},
            {"type": "button", "name": "__pause", "text": "⏸", "action": "pause"},
            {"type": "button", "name": "__play", "text": "▶", "action": "play"},
            {"type": "button", "name": "__stop", "text": "⏹", "action": "stop"},
            {"type": "button", "name": "__next", "text": "⏭", "action": "next"},
        ],
        # volume slider (0-100, the QA_types_ui Player example's setVolume)
        [
            {
                "type": "slider",
                "name": "__setVolume",
                "text": "",
                "min": 0,
                "max": 100,
                "action": "setVolume",
            }
        ],
        # unmute / mute pass their fixed value to setMute (0/1)
        [
            {"type": "button", "name": "__unmute", "text": "🔊", "action": "setMute", "value": 0},
            {"type": "button", "name": "__mute", "text": "🔇", "action": "setMute", "value": 1},
        ],
    ],
    "com.fibaro.multilevelSwitch": [
        [{"type": "label", "name": "__multiswitchValue", "text": "0"}],
        [
            {"type": "button", "name": "__turnOn", "text": "Turn On", "action": "turnOn"},
            {"type": "button", "name": "__turnOff", "text": "Turn Off", "action": "turnOff"},
        ],
        [{"type": "slider", "name": "__setValue", "text": "Brightness", "action": "setValue"}],
    ],
    "com.fibaro.colorController": [
        [
            {"type": "button", "name": "__turnOff", "text": "Off", "action": "turnOff"},
            {"type": "button", "name": "__turnOn", "text": "On", "action": "turnOn"},
        ],
        # each color slider sends setColorComponents with its own component
        # key, like the HC3 client: onAction {"actionName":"setColorComponents",
        # "args":[{"warmWhite":59}], ...} — argKey is the JSON key
        [
            {
                "type": "slider",
                "name": "__red",
                "text": "Red",
                "max": 255,
                "action": "setColorComponents",
                "argKey": "red",
                "color": "#e05a5a",
            }
        ],
        [
            {
                "type": "slider",
                "name": "__green",
                "text": "Green",
                "max": 255,
                "action": "setColorComponents",
                "argKey": "green",
                "color": "#4caf50",
            }
        ],
        [
            {
                "type": "slider",
                "name": "__blue",
                "text": "Blue",
                "max": 255,
                "action": "setColorComponents",
                "argKey": "blue",
                "color": "#4a7fd4",
            }
        ],
        [
            {
                "type": "slider",
                "name": "__warmWhite",
                "text": "Warm white",
                "max": 255,
                "action": "setColorComponents",
                "argKey": "warmWhite",
                "color": "#ffd080",
            }
        ],
        # brightness: the dimmer-style setValue
        [{"type": "slider", "name": "__setValue", "text": "Brightness", "action": "setValue"}],
    ],
    "com.fibaro.multilevelSensor": [
        [{"type": "label", "name": "__multisensorValue", "text": "0"}],
    ],
    # electricMeter/powerMeter use the multilevelSensor dynamic plugin in the
    # HC3 device catalog (their ``view`` lists it), so they get the same
    # default value label — QAs update ``properties.value`` + ``unit`` on
    # their children (the SolarEdge Live pattern) and the viewer shows it.
    "com.fibaro.electricMeter": [
        [{"type": "label", "name": "__multisensorValue", "text": "0"}],
    ],
    "com.fibaro.powerMeter": [
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
    "com.fibaro.rollerShutter": [
        {"property": "value", "id": "__setValue", "prop": "value", "fmt": _int_value},
    ],
    "com.fibaro.remoteRollerShutter": [
        {"property": "value", "id": "__setValue", "prop": "value", "fmt": _int_value},
    ],
    "com.fibaro.player": [
        {"property": "volume", "id": "__setVolume", "prop": "value", "fmt": _int_value},
    ],
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
        # brightness follows the value property (the removed state label's
        # watch died with it)
        {"property": "value", "id": "__setValue", "prop": "value", "fmt": _int_value},
    ],
    "com.fibaro.multilevelSensor": [
        {
            "property": "value",
            "id": "__multisensorValue",
            "prop": "text",
            "fmt": _multisensor_value,
        },
    ],
    "com.fibaro.electricMeter": [
        {
            "property": "value",
            "id": "__multisensorValue",
            "prop": "text",
            "fmt": _multisensor_value,
        },
    ],
    "com.fibaro.powerMeter": [
        {
            "property": "value",
            "id": "__multisensorValue",
            "prop": "text",
            "fmt": _multisensor_value,
        },
    ],
    "com.fibaro.doorSensor": [
        {"property": "value", "id": "__doorSensor", "prop": "text", "fmt": _custom_bin},
    ],
    "com.fibaro.windowSensor": [
        {"property": "value", "id": "__windowSensor", "prop": "text", "fmt": _custom_bin},
    ],
    "com.fibaro.temperatureSensor": [
        {"property": "value", "id": "__temperatureSensor", "prop": "text", "fmt": _temp_value},
    ],
    "com.fibaro.humiditySensor": [
        {"property": "value", "id": "__humiditySensor", "prop": "text", "fmt": _humidity_value},
    ],
    "com.fibaro.hvacSystemAuto": [
        # the setpoint label and slider follow the displayed target (the
        # deadband center in Auto, the active side otherwise); keyed on
        # thermostatMode so every mode/setpoint change re-resolves them
        {
            "property": "thermostatMode",
            "id": "__hvacSetpointValue",
            "prop": "text",
            "fmt": _hvac_target_text,
        },
        {
            "property": "thermostatMode",
            "id": "__hvacSetpoint",
            "prop": "value",
            "fmt": _hvac_target_value,
        },
    ],
    "com.fibaro.hvacSystemCool": [
        # same target, resolved against the cool-only mode set
        {
            "property": "thermostatMode",
            "id": "__hvacSetpointValue",
            "prop": "text",
            "fmt": partial(_hvac_target_text, modes=("Off", "Cool"), default="Cool"),
        },
        {
            "property": "thermostatMode",
            "id": "__hvacSetpoint",
            "prop": "value",
            "fmt": partial(_hvac_target_value, modes=("Off", "Cool"), default="Cool"),
        },
    ],
    "com.fibaro.hvacSystemHeat": [
        {
            "property": "thermostatMode",
            "id": "__hvacSetpointValue",
            "prop": "text",
            "fmt": partial(_hvac_target_text, modes=("Off", "Heat")),
        },
        {
            "property": "thermostatMode",
            "id": "__hvacSetpoint",
            "prop": "value",
            "fmt": partial(_hvac_target_value, modes=("Off", "Heat")),
        },
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
    if callable(rows):
        # a builder (the hvacSystemAuto): the rows depend on the device's
        # current properties and are re-resolved on every poll
        rows = rows(properties)
    values: dict[str, dict[str, Any]] = {}
    for rule in EMBEDDED_WATCHES.get(device_type) or ():
        raw = properties.get(rule["property"])
        if raw is None:
            continue
        fmt = rule["fmt"]
        if callable(fmt):
            value: Any = fmt(raw, properties)
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
