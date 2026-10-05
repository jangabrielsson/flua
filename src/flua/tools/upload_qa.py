"""uploadQA: package an unpacked QA project and upload it to the HC3.

The target is one of:

- a main file (``main.lua`` or anything) — uploaded as a NEW QuickApp;
- a downloaded ``<Name>_main_<id>.lua`` — updates THAT QA on the HC3:
  files, name, the standard properties (UI structures, description) and
  interfaces, each only when it changed;
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

# The standard properties updateQA syncs from the package to the device:
# the UI structures and the description. quickAppVariables deliberately stay
# out — they are initializers, the user's runtime values win.
_UPDATE_PROPERTIES = ("viewLayout", "uiView", "uiCallbacks", "useUiView", "userDescription")


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


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _update_existing(
    engine: Any, parser: argparse.ArgumentParser, qa_id: int, fqa: dict[str, Any]
) -> int:
    """Sync an existing QA to the package: files, name, the standard
    properties (UI structures, description), and interfaces — each only when
    it actually changed. The device type cannot change on the HC3."""
    device, status = engine.api.dispatch_hc3("GET", f"/devices/{qa_id}")
    if status != 200 or not isinstance(device, dict):
        parser.error(f"cannot read QA {qa_id} (HTTP {status})")
    if device.get("type") != fqa.get("type"):
        parser.error(
            f"cannot change the device type ({device.get('type')} -> "
            f"{fqa.get('type')}) — upload as a new QA instead"
        )
    updated: list[str] = []
    files = fqa_files(fqa)
    _data, status = engine.api.dispatch_hc3("PUT", f"/quickApp/{qa_id}/files", files)
    if status not in (200, 204):
        parser.error(f"cannot update QA {qa_id} files (HTTP {status})")
    if fqa.get("name") and device.get("name") != fqa["name"]:
        _data, status = engine.api.dispatch_hc3(
            "PUT", f"/devices/{qa_id}", {"name": fqa["name"]}
        )
        if status not in (200, 204):
            parser.error(f"cannot rename QA {qa_id} (HTTP {status})")
        updated.append("name")
    initial = fqa.get("initialProperties") or {}
    current = device.get("properties") or {}
    for key in _UPDATE_PROPERTIES:
        if key in initial and not _same(current.get(key), initial[key]):
            _data, status = engine.api.dispatch_hc3(
                "POST",
                "/plugins/updateProperty",
                {"deviceId": qa_id, "propertyName": key, "value": initial[key]},
            )
            if status not in (200, 204):
                parser.error(f"cannot update QA {qa_id} property {key} (HTTP {status})")
            updated.append(key)
    wanted = set(fqa.get("initialInterfaces") or [])
    have = set(device.get("interfaces") or [])
    if wanted != have:
        for action, interfaces in (("add", wanted - have), ("delete", have - wanted)):
            if interfaces:
                _data, status = engine.api.dispatch_hc3(
                    "POST",
                    "/plugins/interfaces",
                    {"deviceId": qa_id, "action": action, "interfaces": sorted(interfaces)},
                )
                if status not in (200, 204):
                    parser.error(f"cannot update QA {qa_id} interfaces (HTTP {status})")
        updated.append("interfaces")
    detail = f", {', '.join(updated)}" if updated else ""
    print(f"updated QA {qa_id} from {fqa['name']} ({len(files)} files{detail})")
    return 0


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    main_path, qa_id = _resolve_target(parser, args.target)
    try:
        fqa, _ = build_fqa(main_path)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    if qa_id is not None:
        # the target names an existing QA: sync files, name, properties, UI
        return _update_existing(engine, parser, qa_id, fqa)
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
