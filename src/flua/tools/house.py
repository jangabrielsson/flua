"""house: the house around the QA as one JSON document.

The data source for hub-aware completions in the VS Code extension: device
IDs with names and rooms, global variable names, scene IDs with names, and
custom event names. Resolution order:

1. HC3 credentials in the .env chain → the real hub (devices, rooms,
   /globalVariables, /scenes, /customEvents).
2. A seed/db file (--db) → the simulated house (the state_tool loader).
3. Neither → an empty house (a QA-only run has none).

Always prints one JSON document on stdout; the shape is the contract:

    {"devices": [{"id": 45, "name": "Kitchen light",
                  "room": "Kitchen", "type": "com.fibaro.binarySwitch"}],
     "globals": ["AlarmState"],
     "scenes": [{"id": 3, "name": "Evening lights"}],
     "customEvents": ["DoorOpened"]}
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from ..environment import EnvChain
from ..hc3 import Hc3Remote
from .state_tool import load_state

NAME = "house"
HELP = "the house (devices, globals, scenes, custom events) as one JSON document"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        metavar="FILE",
        help="seed/db file for the simulated house (used when no HC3 credentials exist)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="hub request timeout (default 5s)",
    )


def _get(remote: Hc3Remote, path: str, default: Any = None) -> tuple[Any, int]:
    try:
        data, status = remote.request("GET", path)
    except Exception as exc:
        raise RuntimeError(f"cannot read {path}: {exc}") from exc
    return data if data is not None else default, status


def _names(entries: Any) -> list[str]:
    """Global-variable / custom-event entries as names: the HC3 serves both
    as objects with a name field and (custom events) sometimes as bare
    strings — accept either."""
    names = []
    for entry in entries or []:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict) and entry.get("name"):
            names.append(str(entry["name"]))
    return names


def _hub_house(remote: Hc3Remote, timeout: float) -> dict[str, Any]:
    rooms_by_id: dict[int, str] = {}
    rooms, status = _get(remote, "/rooms", [])
    if status == 200 and isinstance(rooms, list):
        for room in rooms:
            if isinstance(room, dict) and room.get("id") is not None and room.get("name"):
                rooms_by_id[int(room["id"])] = str(room["name"])

    devices_out: list[dict[str, Any]] = []
    devices, status = _get(remote, "/devices", [])
    if status != 200 or not isinstance(devices, list):
        raise RuntimeError(f"cannot list devices (HTTP {status})")
    for dev in devices:
        if not isinstance(dev, dict) or dev.get("id") is None:
            continue
        devices_out.append(
            {
                "id": dev.get("id"),
                "name": dev.get("name"),
                "type": dev.get("type"),
                "room": rooms_by_id.get(dev.get("roomID"))
                if dev.get("roomID") is not None
                else None,
            }
        )
    devices_out.sort(key=lambda d: (d["id"] is None, d["id"] or 0))

    globals_entries, status = _get(remote, "/globalVariables", [])
    if status != 200:
        raise RuntimeError(f"cannot list global variables (HTTP {status})")

    scenes_out: list[dict[str, Any]] = []
    scenes, status = _get(remote, "/scenes", [])
    if status != 200 or not isinstance(scenes, list):
        raise RuntimeError(f"cannot list scenes (HTTP {status})")
    for scene in scenes:
        if isinstance(scene, dict) and scene.get("id") is not None:
            scenes_out.append({"id": scene.get("id"), "name": scene.get("name")})
    scenes_out.sort(key=lambda s: (s["id"] is None, s["id"] or 0))

    events, status = _get(remote, "/customEvents", [])
    if status != 200:
        raise RuntimeError(f"cannot list custom events (HTTP {status})")

    return {
        "devices": devices_out,
        "globals": sorted(_names(globals_entries)),
        "scenes": scenes_out,
        "customEvents": sorted(_names(events)),
    }


def _sim_house(db_path: str, parser: argparse.ArgumentParser) -> dict[str, Any]:
    state = load_state(db_path, parser)
    rooms = state.rooms
    devices_out = []
    for dev in state.devices.values():
        devices_out.append(
            {
                "id": dev.get("id"),
                "name": dev.get("name"),
                "type": dev.get("type"),
                "room": rooms[dev["roomID"]].get("name")
                if dev.get("roomID") is not None and dev["roomID"] in rooms
                else None,
            }
        )
    devices_out.sort(key=lambda d: (d["id"] is None, d["id"] or 0))
    scenes_out = [
        {"id": scene.get("id"), "name": scene.get("name")}
        for scene in state.scenes.values()
        if scene.get("id") is not None
    ]
    scenes_out.sort(key=lambda s: (s["id"] is None, s["id"] or 0))
    return {
        "devices": devices_out,
        "globals": sorted(state.global_variables),
        "scenes": scenes_out,
        "customEvents": sorted(_names(state.custom_events)),
    }


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    chain = EnvChain()
    url = chain.get("HC3_URL")
    if url:
        remote = Hc3Remote(
            url, chain.get("HC3_USER"), chain.get("HC3_PASSWORD"), timeout=args.timeout
        )
        try:
            doc = _hub_house(remote, args.timeout)
        except RuntimeError as exc:
            parser.error(str(exc))
        print(json.dumps(doc))
        return 0
    if args.db:
        print(json.dumps(_sim_house(args.db, parser)))
        return 0
    # no hub, no house: an honest empty document (a QA-only run)
    print(json.dumps({"devices": [], "globals": [], "scenes": [], "customEvents": []}))
    return 0
