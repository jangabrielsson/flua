"""uploadQA: package an unpacked QA project and upload it to the HC3.

The target is one of:

- a main file (``main.lua`` or anything) — uploaded as a NEW QuickApp;
- a downloaded ``<Name>_main_<id>.lua`` — updates THAT QA on the HC3;
- a QA name — the tool finds ``<sanitized-name>_main_<id>.lua`` in the
  current directory (newest id wins) and updates that QA.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any

from ..engine import sanitize_filename
from .common import build_fqa, fqa_files, hc3_engine

NAME = "uploadQA"
HELP = (
    "package an unpacked QA project and upload it to the HC3 "
    "(new QA, or the id in a downloaded <Name>_main_<id>.lua)"
)

_MAIN_RE = re.compile(r"^(.*)_main_(\d+)\.lua$")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "target",
        help="the QA main file, a downloaded <Name>_main_<id>.lua (updates "
        "that QA), or a QA name whose project files live in the current "
        "directory",
    )
    parser.add_argument(
        "--room", type=int, default=None, metavar="ID", help="place the QA in this room"
    )


def _resolve_target(parser: argparse.ArgumentParser, target: str) -> tuple[str, int | None]:
    """The project main path and the HC3 id to update, if the target names one."""
    path = Path(target)
    if path.is_file():
        match = _MAIN_RE.match(path.name)
        return str(path), int(match.group(2)) if match else None
    # not a file: a QA name — find its downloaded project in the cwd
    prefix = sanitize_filename(target) + "_"
    mains = sorted(Path.cwd().glob(re.escape(prefix) + "main_*.lua"))
    if not mains:
        parser.error(
            f"no project found for QA {target!r} — expected "
            f"{prefix}main_<id>.lua in the current directory"
        )
    main = mains[-1]  # several downloads: the newest id wins
    match = _MAIN_RE.match(main.name)
    return str(main), int(match.group(2)) if match else None


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    main_path, qa_id = _resolve_target(parser, args.target)
    try:
        fqa, _ = build_fqa(main_path)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    if qa_id is not None:
        # the target names an existing QA: update its files
        files = fqa_files(fqa)
        _data, status = engine.api.dispatch_hc3("PUT", f"/quickApp/{qa_id}/files", files)
        if status not in (200, 204):
            parser.error(f"cannot update QA {qa_id} (HTTP {status})")
        print(f"updated QA {qa_id} from {fqa['name']} ({len(files)} files)")
        return 0
    body: dict[str, Any] = {
        "file": base64.b64encode(json.dumps(fqa).encode("utf-8")).decode("ascii")
    }
    if args.room is not None:
        body["roomId"] = args.room
    device, status = engine.api.dispatch_hc3("POST", "/quickApp", body)
    if status not in (200, 201) or not isinstance(device, dict):
        parser.error(f"cannot upload QA to the HC3 (HTTP {status})")
    print(f"uploaded {fqa['name']} — HC3 device id {device.get('id')}")
    return 0
