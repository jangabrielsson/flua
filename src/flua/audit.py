"""``flua audit`` — coverage of the HC3 surface the sim implements.

Two sections:

- **REST routes**: every endpoint in ``docs/specs/hc3-api.json`` (the
  distilled official swagger) classified simulated (a compiled route
  answers it offline) or not (forwarded to the real HC3 in online mode).
- **Device catalog**: which catalog types the sim gives light-like
  behavior (the layer-1 emulation is gated on the ``light`` interface),
  which declare light actions without that interface (a gap — the sim
  never emulates them), and which are inert shells.

``tests/test_audit.py`` pins the current numbers, so coverage can only go
up (and spec drift is noticed).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .api import route_match
from .devices import skeleton_for

# the spec ships in the wheel as setup_templates package data (the same
# copy the sync test pins against docs/specs/hc3-api.json)
_SPEC_PATH = (
    Path(__file__).resolve().parent
    / "setup_templates"
    / "docs"
    / "specs"
    / "hc3-api.json"
)
_CATALOG_PATH = Path(__file__).resolve().parent / "devices" / "devices.json"
_HIERARCHY_PATH = Path(__file__).resolve().parent / "devices" / "hierarchy.json"
_TEMPLATES_PATH = (
    Path(__file__).resolve().parent
    / "setup_templates"
    / "github"
    / "skills"
    / "quickapp-types"
    / "templates"
)
_LIGHT_ACTIONS = ("turnOn", "turnOff", "setValue")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable result (one JSON document)",
    )


def spec_endpoints() -> list[dict[str, Any]]:
    document = json.loads(_SPEC_PATH.read_text(encoding="utf-8"))
    return document["endpoints"]


def route_coverage() -> dict[str, Any]:
    """Classify every spec endpoint against the compiled route table."""
    simulated: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for endpoint in spec_endpoints():
        method = str(endpoint.get("method") or "").upper()
        path = str(endpoint.get("path") or "")
        if not method or not path:
            continue
        (simulated if route_match(method, path) else missing).append(endpoint)
    return {"total": len(simulated) + len(missing), "simulated": simulated, "missing": missing}


def device_coverage() -> dict[str, Any]:
    catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    modeled: list[str] = []
    light_gap: list[str] = []
    other_actions: list[str] = []
    inert: list[str] = []
    for type_name, device in catalog.items():
        interfaces = device.get("interfaces") or []
        actions = device.get("actions") or {}
        if "light" in interfaces:
            modeled.append(type_name)
        elif any(action in actions for action in _LIGHT_ACTIONS):
            light_gap.append(type_name)
        elif actions:
            other_actions.append(type_name)
        else:
            inert.append(type_name)
    return {
        "total": len(catalog),
        "lightModeled": modeled,
        "lightActionsWithoutInterface": light_gap,
        "otherActions": other_actions,
        "inert": inert,
    }


def hierarchy_coverage() -> dict[str, Any]:
    """The offline type hierarchy: how many HC3 types it knows and how many
    resolve (directly or through ancestors) to a cataloged type."""
    try:
        raw = json.loads(_HIERARCHY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"total": 0, "inCatalog": 0, "resolvable": 0, "firmware": None}
    parents = raw.get("parents")
    if not isinstance(parents, dict):
        parents = {}
    catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    resolvable = 0
    for child in parents:
        current = child
        seen: set[str] = set()
        while current in parents and current not in seen:
            seen.add(current)
            current = parents[current]
            if current in catalog:
                resolvable += 1
                break
    return {
        "total": len(parents),
        "inCatalog": sum(1 for type_name in parents if type_name in catalog),
        "resolvable": resolvable,
        "firmware": (raw.get("meta") or {}).get("firmware"),
    }


def template_coverage() -> dict[str, Any]:
    """The QA templates (quickapp-types): the types people actually declare
    with --%%type. Each template must resolve to a skeleton, or newQA/run
    fails with an unknown-type error."""
    resolvable: list[str] = []
    unresolvable: list[str] = []
    for path in sorted(_TEMPLATES_PATH.glob("*.lua")):
        match = re.search(r"--%%type:(\S+)", path.read_text(encoding="utf-8"))
        declared = match.group(1) if match else None
        if declared and skeleton_for(declared) is not None:
            resolvable.append(path.stem)
        else:
            unresolvable.append(path.stem)
    return {
        "total": len(resolvable) + len(unresolvable),
        "resolvable": resolvable,
        "unresolvable": unresolvable,
    }


def _areas(endpoints: list[dict[str, Any]]) -> dict[str, int]:
    areas = Counter(
        str(endpoint.get("path") or "").split("/")[1].split("?")[0] for endpoint in endpoints
    )
    return dict(sorted(areas.items()))


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    routes = route_coverage()
    devices = device_coverage()
    hierarchy = hierarchy_coverage()
    templates = template_coverage()
    if args.json:
        print(
            json.dumps(
                {
                    "routes": {
                        "total": routes["total"],
                        "simulated": len(routes["simulated"]),
                        "missing": len(routes["missing"]),
                    },
                    "devices": {
                        "total": devices["total"],
                        "lightModeled": len(devices["lightModeled"]),
                        "lightActionsWithoutInterface": len(
                            devices["lightActionsWithoutInterface"]
                        ),
                        "otherActions": len(devices["otherActions"]),
                        "inert": len(devices["inert"]),
                    },
                    "hierarchy": hierarchy,
                    "templates": {
                        "total": templates["total"],
                        "resolvable": len(templates["resolvable"]),
                        "unresolvable": templates["unresolvable"],
                    },
                }
            )
        )
        return 0
    total = routes["total"]
    simulated = len(routes["simulated"])
    print("flua audit")
    print("REST routes (docs/specs/hc3-api.json)")
    print(f"  {simulated} of {total} simulated ({100 * simulated // total}%)")
    print(f"  {len(routes['missing'])} not simulated (forwarded to the HC3 online)")
    areas = _areas(routes["missing"])
    print("  not simulated by area: " + ", ".join(f"{k} {v}" for k, v in areas.items()))
    print("Device catalog (src/flua/devices/devices.json)")
    print(
        f"  {devices['total']} types: {len(devices['lightModeled'])} light-modeled, "
        f"{len(devices['lightActionsWithoutInterface'])} light-actions-without-interface, "
        f"{len(devices['otherActions'])} other-actions, {len(devices['inert'])} inert"
    )
    if devices["lightActionsWithoutInterface"]:
        print(
            "  specific device captures declare light actions but not the light "
            "interface — QAs use a parent type instead: "
            + ", ".join(sorted(devices["lightActionsWithoutInterface"])[:8])
            + (", ..." if len(devices["lightActionsWithoutInterface"]) > 8 else "")
        )
    firmware = f" (firmware {hierarchy['firmware']})" if hierarchy.get("firmware") else ""
    print(
        f"Type hierarchy (devices/hierarchy.json): {hierarchy['total']} types{firmware}, "
        f"{hierarchy['inCatalog']} in the catalog, "
        f"{hierarchy['resolvable']} resolvable to a catalog ancestor"
    )
    print(
        f"QA templates (quickapp-types): {templates['total']} templates, "
        f"{len(templates['resolvable'])} with resolvable types"
    )
    if templates["unresolvable"]:
        print(
            "  unresolvable (newQA/run fails — remap to a parent type): "
            + ", ".join(templates["unresolvable"])
        )
    return 0
