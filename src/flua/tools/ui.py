"""ui: print a QA's UI as text — elements, callbacks, options, values.

The browser viewer needs a browser; agents and quick eyeball checks need
text. This renders the QA's compiled UI (the active format: the legacy
viewLayout by default, uiView with --%%useUiView:true) as one line per
element. ``--device ID`` instead fetches an HC3 device's UI (the proxy a
mode:proxy run deployed, edited in the HC3's editor) and renders it back
to ``--%%u`` rows plus the raw UI JSON — the lossless form to paste into
a QA.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from ..ui import ui_to_u_rows
from .common import build_fqa, hc3_engine

NAME = "ui"
HELP = (
    "print a QA's DECLARED UI as text (elements, callbacks, options) — static, "
    "not live state; --device ID fetches an HC3 device's UI and renders it "
    "back to --%%u rows + the raw JSON; for post-init values and callback "
    "behavior see examples/ui-interaction-test.lua"
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("script", nargs="?", help="the QA main file (omit with --device)")
    parser.add_argument(
        "--device",
        type=int,
        help="render the UI of an HC3 device by id (e.g. the proxy of a "
        "--%%mode:proxy run, edited in the HC3's UI editor) instead of a script",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="structured dump instead of text: {name, type, useUiView, elements, callbacks}",
    )


def device_ui(device: dict[str, Any]) -> tuple[str, list[str], Any]:
    """(title, --%%u rows, raw UI JSON) for an HC3 device dict — the
    inverse-export view of its UI properties (ui_to_u_rows, the same
    converter downloadQA uses). The shorthand is lossy: unknown component
    kinds degrade to labels, so the raw JSON travels alongside."""
    properties = device.get("properties") or {}
    rows = ui_to_u_rows(
        ui_view=properties.get("uiView"),
        view_layout=properties.get("viewLayout"),
        ui_callbacks=properties.get("uiCallbacks"),
    )
    raw = (
        properties.get("uiView")
        if properties.get("useUiView")
        else properties.get("viewLayout")
    )
    title = f'HC3 device "{device.get("name")}" ({device.get("type", "?")})'
    return title, rows, raw


def _callback_map(initial: dict[str, Any]) -> dict[str, dict[str, str]]:
    """uiCallbacks ({name, eventType, callback} entries) ->
    {name: {eventType: callback}}."""
    callbacks: dict[str, dict[str, str]] = {}
    for entry in initial.get("uiCallbacks") or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        callbacks.setdefault(str(entry["name"]), {})[str(entry.get("eventType", ""))] = str(
            entry.get("callback", "")
        )
    return callbacks


def _callback_suffix(cbs: dict[str, str] | None, name: str, *events: str) -> str:
    if not cbs or not name:
        return ""
    for event in events:
        if event in cbs:
            return f" -> {event}={cbs[event]}"
    return ""


def _options_text(component: dict[str, Any]) -> str:
    options = component.get("options") or []
    if not options:
        return ""
    rendered = ", ".join(
        f"{o.get('text', '')}={o.get('value', '')}" for o in options if isinstance(o, dict)
    )
    return f" [{rendered}]"


def _selected(component: dict[str, Any]) -> str:
    value = component.get("value")
    if value not in (None, ""):
        return str(value)
    values = component.get("values") or []
    if values:
        return "{" + ",".join(str(v) for v in values) + "}"
    return ""


def _component_line(component: dict[str, Any], cbs: dict[str, dict[str, str]]) -> str | None:
    typ = str(component.get("type", "?"))
    name = str(component.get("name") or "")
    text = str(component.get("text") or "")
    label = f'"{text}"' if text else ""
    if typ in ("vertical", "horizontal"):
        return None  # row containers carry nothing of their own
    if typ == "label":
        return f"label {name} {label}".strip()
    if typ == "text":
        return f"text {label}".strip()
    if typ == "space":
        return "space"
    if typ == "button":
        cbs_name = cbs.get(name)
        cb = _callback_suffix(cbs_name, name, "onReleased", "onLongPressed")
        return f"button {name} {label}{cb}".strip()
    if typ == "slider":
        selected = _selected(component)
        low = component.get("min", "")
        high = component.get("max", "")
        return (
            f"slider {name} {label} [{low}..{high}] = {selected}"
            f"{_callback_suffix(cbs.get(name), name, 'onChanged')}"
        ).strip()
    if typ in ("select", "multi"):
        selected = _selected(component)
        assignment = f" = {selected}" if selected else ""
        return (
            f"{typ} {name} {label}{assignment}"
            f"{_options_text(component)}"
            f"{_callback_suffix(cbs.get(name), name, 'onToggled')}"
        ).strip()
    if typ == "switch":
        return f"switch {name} {label} = {_selected(component)}".strip()
    return f"{typ} {name} {label}".strip()


def _walk_components(components: Any):
    """Yield the leaf components, descending into row containers
    (vertical/horizontal) — the legacy viewLayout nests buttons inside
    horizontal rows, one level (or more) deep."""
    for component in components or []:
        if not isinstance(component, dict):
            continue
        if str(component.get("type")) in ("vertical", "horizontal"):
            yield from _walk_components(component.get("components"))
        else:
            yield component


def _components(initial: dict[str, Any]) -> list[dict[str, Any]]:
    """The active format's components, flattened (containers descend)."""
    if initial.get("useUiView"):
        rows = initial.get("uiView") or []
        components: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                components.extend(_walk_components(row.get("components")))
        return components
    jason = (initial.get("viewLayout") or {}).get("$jason") or {}
    sections = ((jason.get("body") or {}).get("sections") or {}).get("items") or []
    components = []
    for item in sections:
        if isinstance(item, dict):
            components.extend(_walk_components(item.get("components")))
    return components


def _render_view_layout(layout: Any, cbs: dict[str, dict[str, str]]) -> list[str]:
    jason = (layout or {}).get("$jason") or {}
    sections = ((jason.get("body") or {}).get("sections") or {}).get("items") or []
    lines: list[str] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        for component in _walk_components(item.get("components")):
            line = _component_line(component, cbs)
            if line:
                lines.append(line)
    return lines


def _render_ui_view(rows: Any, cbs: dict[str, dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for component in _walk_components(row.get("components")):
            line = _component_line(component, cbs)
            if line:
                lines.append(line)
    return lines


def ui_dump(script: str) -> dict[str, Any]:
    """The structured UI dump: {name, type, useUiView, elements, callbacks}.
    Shared by the --tool ui --json output and the MCP qa_ui tool."""
    fqa, _ = build_fqa(script)
    initial = fqa.get("initialProperties") or {}
    return {
        "name": fqa.get("name"),
        "type": fqa.get("type"),
        "useUiView": bool(initial.get("useUiView")),
        "elements": _components(initial),
        "callbacks": initial.get("uiCallbacks") or [],
    }


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.device is not None:
        if args.script:
            parser.error("pass either a script or --device, not both")
        engine = hc3_engine(parser)
        if engine.hc3 is None:
            parser.error("online mode required (HC3 credentials from the environment chain)")
        device, status = engine.hc3.request("GET", f"/devices/{args.device}")
        if status != 200 or not isinstance(device, dict):
            parser.error(f"HC3 device {args.device}: HTTP {status}")
        title, rows, raw = device_ui(device)
        print(title)
        if not rows:
            print("  (no UI)")
        else:
            for row in rows:
                print("  --%%u:" + row)
            print(
                "  # the shorthand is lossy (unknown kinds degrade to labels) — "
                "the raw UI JSON below is the full picture"
            )
        print(json.dumps(raw, indent=1))
        return 0
    if not args.script:
        parser.error("pass a script or --device")
    try:
        fqa, _ = build_fqa(args.script)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    initial = fqa.get("initialProperties") or {}
    cbs = _callback_map(initial)
    if args.json:
        # structured dump: agents read elements/callbacks/values without
        # parsing prose — the same components the text renderer walks
        print(json.dumps(ui_dump(args.script)))
        return 0
    print(f'QA "{fqa.get("name")}" ({fqa.get("type", "?")})')
    if initial.get("useUiView"):
        lines = _render_ui_view(initial.get("uiView"), cbs)
    else:
        lines = _render_view_layout(initial.get("viewLayout"), cbs)
    if not lines:
        print("  (no UI)")
        return 0
    for line in lines:
        print("  " + line)
    return 0
