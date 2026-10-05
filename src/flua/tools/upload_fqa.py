"""uploadFQA: upload a .fqa package to the HC3 as a NEW QuickApp.

Unlike uploadQA (which packages an unpacked project first), this tool takes
a ready-made package — your own, or one another HC3 exported — and creates
a new QA from it. Offline (no HC3 credentials) the same call creates the QA
in the simulated HC3.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from .common import hc3_engine

NAME = "uploadFQA"
HELP = "upload a .fqa package to the HC3 as a NEW QuickApp"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("package", help="the .fqa file")
    parser.add_argument(
        "--room", type=int, default=None, metavar="ID", help="place the QA in this room"
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    path = Path(args.package)
    if not path.exists():
        parser.error(f"cannot open {args.package}: no such file")
    try:
        fqa = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        parser.error(f"invalid fqa JSON: {exc}")
    if not isinstance(fqa, dict) or not isinstance(fqa.get("files"), list):
        parser.error("fqa file must contain a JSON object with a files array")
    engine = hc3_engine(parser)
    body: dict[str, object] = {
        "file": base64.b64encode(json.dumps(fqa).encode("utf-8")).decode("ascii")
    }
    if args.room is not None:
        body["roomId"] = args.room
    device, status = engine.api.dispatch_hc3("POST", "/quickApp", body)
    if status not in (200, 201) or not isinstance(device, dict):
        parser.error(f"cannot upload QA to the HC3 (HTTP {status})")
    print(f"uploaded {fqa.get('name')} — HC3 device id {device.get('id')}")
    return 0
