"""createDB: build an offline db from the real HC3's identity and location."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import hc3_engine

NAME = "createDB"
HELP = "build an offline db from the HC3 (device 1, location, panels)"


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


def grab_db(engine) -> dict:
    """Read the HC3's identity/location endpoints into a flua db document."""

    def get(path: str):
        data, status = engine.api.dispatch_hc3("GET", path, None)
        if status != 200:
            raise RuntimeError(f"GET {path} failed (HTTP {status})")
        return data

    location = get("/settings/location") or {}
    info = get("/settings/info") or {}
    dev1 = get("/devices/1") or {}
    name = dev1.get("name") or info.get("hcName") or "HC3"
    props = dev1.get("properties") or {}
    doc: dict = {
        "version": 1,
        "location": {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
        },
        "devices": [
            {
                "id": 1,
                "name": name,
                "type": "HC3",
                "properties": {
                    "sunriseHour": props.get("sunriseHour", "00:00"),
                    "sunsetHour": props.get("sunsetHour", "00:00"),
                },
            }
        ],
    }
    panels = get("/panels/location")
    if isinstance(panels, list) and panels:
        doc["familyLocations"] = panels
    return doc


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    output = Path(args.output)
    if output.exists() and not args.force:
        parser.error(f"{output} exists — pass --force to overwrite")
    try:
        doc = grab_db(engine)
    except RuntimeError as exc:
        parser.error(str(exc))
    output.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output} (device 1: {doc['devices'][0]['name']})")
    return 0
