"""createDB: build an offline db from the real HC3's identity and location
(--full: the whole house — devices, rooms, sections, global variables,
scenes, alarm partitions, profiles)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import hc3_engine

NAME = "createDB"
HELP = "build an offline db from the HC3 (device 1, location, panels; --full: the house)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default="db.json",
        help="the db file to write (default: db.json)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite an existing file",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="capture the whole house: physical devices, rooms, sections, "
        "global variables, scenes, alarm partitions and profiles "
        "(QuickApps are excluded — they are code, not house data)",
    )


def _get(engine, path: str):
    data, status = engine.api.dispatch_hc3("GET", path, None)
    if status != 200:
        raise RuntimeError(f"GET {path} failed (HTTP {status})")
    return data


def _identity_doc(engine) -> dict:
    """The minimal identity/location db: device 1 with its real sun times."""
    location = _get(engine, "/settings/location") or {}
    info = _get(engine, "/settings/info") or {}
    dev1 = _get(engine, "/devices/1") or {}
    name = dev1.get("name") or info.get("hcName") or "HC3"
    props = dev1.get("properties") or {}
    doc = {
        "version": 1,
        "location": {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
        },
        "devices": [
            {
                "id": 1,
                "name": name,
                "type": dev1.get("type") or "com.fibaro.zwavePrimaryController",
                "properties": {
                    "sunriseHour": props.get("sunriseHour", "00:00"),
                    "sunsetHour": props.get("sunsetHour", "00:00"),
                },
            }
        ],
    }
    panels = _get(engine, "/panels/location")
    if isinstance(panels, list) and panels:
        doc["familyLocations"] = panels
    return doc


def _full_doc(engine) -> dict:
    """The whole house in seed shape — what flua can actually serve:
    physical devices (QAs excluded — they are code, not house data), rooms,
    sections, global variables, scenes, alarm partitions, profiles, plus
    the identity/location core (location + panels; device 1 comes from the
    device list)."""
    location = _get(engine, "/settings/location") or {}
    doc: dict = {
        "version": 1,
        "location": {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
        },
    }
    devices = _get(engine, "/devices")
    if isinstance(devices, list):
        doc["devices"] = [
            device
            for device in devices
            if "quickApp" not in (device.get("interfaces") or [])
        ]
    rooms = _get(engine, "/rooms")
    if isinstance(rooms, list):
        doc["rooms"] = rooms
    sections = _get(engine, "/sections")
    if isinstance(sections, list):
        doc["sections"] = sections
    variables = _get(engine, "/globalVariables")
    if isinstance(variables, list):
        doc["globalVariables"] = {
            str(entry.get("name")): {
                "value": "" if entry.get("value") is None else str(entry.get("value")),
                "modified": int(entry.get("modified") or 0),
            }
            for entry in variables
            if entry.get("name") is not None
        }
    scenes = _get(engine, "/scenes")
    if isinstance(scenes, list):
        doc["scenes"] = scenes
    partitions = _get(engine, "/alarms/v1/partitions")
    if isinstance(partitions, list):
        doc["alarms"] = partitions
    profiles = _get(engine, "/profiles")
    if isinstance(profiles, dict) and isinstance(profiles.get("profiles"), list):
        doc["profiles"] = profiles["profiles"]
    panels = _get(engine, "/panels/location")
    if isinstance(panels, list) and panels:
        doc["familyLocations"] = panels
    return doc


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    output = Path(args.output)
    if output.exists() and not args.force:
        parser.error(f"{output} exists — pass --force to overwrite")
    try:
        doc = _full_doc(engine) if args.full else _identity_doc(engine)
    except RuntimeError as exc:
        parser.error(str(exc))
    output.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output} (device 1: {doc['devices'][0]['name']})")
    return 0
