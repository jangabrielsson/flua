"""ui: print a QA's UI as text — elements, callbacks, options, values.

The browser viewer needs a browser; agents and quick eyeball checks need
text. This renders the QA's compiled UI (the active format: the legacy
viewLayout by default, uiView with --%%useUiView:true) as one line per
element.
"""

from __future__ import annotations

import argparse
from typing import Any

from .common import build_fqa

NAME = "ui"
HELP = "print a QA's UI as text (elements, callbacks, options) — no browser needed"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("script", help="the QA main file")


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


def _render_view_layout(layout: Any, cbs: dict[str, dict[str, str]]) -> list[str]:
    jason = (layout or {}).get("$jason") or {}
    sections = ((jason.get("body") or {}).get("sections") or {}).get("items") or []
    lines: list[str] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        for component in item.get("components") or []:
            if isinstance(component, dict):
                line = _component_line(component, cbs)
                if line:
                    lines.append(line)
    return lines


def _render_ui_view(rows: Any, cbs: dict[str, dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for component in row.get("components") or []:
            if isinstance(component, dict):
                line = _component_line(component, cbs)
                if line:
                    lines.append(line)
    return lines


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    try:
        fqa, _ = build_fqa(args.script)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    initial = fqa.get("initialProperties") or {}
    cbs = _callback_map(initial)
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
