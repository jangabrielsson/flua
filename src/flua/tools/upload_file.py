"""uploadFile: push a single QA file to its QA on the HC3.

The VS Code task flow (a tasks.json entry with ``${file}``): edit one file of
a downloaded QA project and send just that file to the HC3 — no full
re-upload, no project lookup. The target QA is read from the file's own
header: downloadQA writes ``--%%deviceId:<id>`` and ``--%%qaFile:<name>``
into every unpacked file; for files downloaded by an older flua, the
``<Name>_<file>_<id>.lua`` filename convention is the fallback.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from ..config import DEVICE_ID_DIRECTIVE, QA_FILE_DIRECTIVE, parse_annotations
from ..engine import sanitize_filename
from .common import hc3_engine

NAME = "uploadFile"
HELP = "update one QA file on the HC3 (reads --%%deviceId/--%%qaFile from the file)"

_NAME_PATTERN = re.compile(r"^(?P<prefix>.+)_(?P<name>[^_]+)_(?P<id>\d+)\.lua$")


def _metadata(source: str) -> tuple[int | None, str | None]:
    """The --%%deviceId/--%%qaFile directives downloadQA writes into files."""
    annotations = parse_annotations(source)
    try:
        return int(annotations.get(DEVICE_ID_DIRECTIVE)), str(annotations.get(QA_FILE_DIRECTIVE))
    except (TypeError, ValueError):
        return None, None


def _metadata_from_filename(filename: str) -> tuple[int | None, str | None]:
    """The pre-directive download layout: <Name>_<file>_<id>.lua."""
    match = _NAME_PATTERN.match(filename)
    if match is None:
        return None, None
    return int(match.group("id")), match.group("name")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("script", help="the QA file to upload")


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    path = Path(args.script)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        parser.error(f"cannot open {args.script}: {exc}")
    device_id, qa_name = _metadata(source)
    if device_id is None or qa_name is None:
        device_id, qa_name = _metadata_from_filename(path.name)
    if device_id is None or qa_name is None:
        parser.error(
            f"{args.script}: no --%%{DEVICE_ID_DIRECTIVE}/{QA_FILE_DIRECTIVE} directives and "
            "the file name is not a <Name>_<file>_<id>.lua download — run --tool downloadQA "
            "or add the directives"
        )
    is_main = qa_name == "main"
    engine = hc3_engine(parser)
    # stale-directive guard: the file may have been copied out of another QA's
    # project — warn when the target QA's name no longer matches the file name
    match = _NAME_PATTERN.match(path.name)
    if match is not None:
        device, status = engine.api.dispatch_hc3("GET", f"/devices/{device_id}")
        if status == 200 and isinstance(device, dict) and device.get("name"):
            if sanitize_filename(str(device["name"])) != match.group("prefix"):
                print(
                    f"warning: file name says '{match.group('prefix')}' but device "
                    f"{device_id} is named '{device['name']}' — continuing (directive wins)"
                )
    files = [{"name": qa_name, "type": "lua", "isMain": is_main, "content": source}]
    _data, status = engine.api.dispatch_hc3("PUT", f"/quickApp/{device_id}/files", files)
    if status not in (200, 204):
        parser.error(f"cannot update {args.script} in QA {device_id} (HTTP {status})")
    restarted = " — the QA restarts" if is_main else ""
    print(f"updated {path.name} -> QA {device_id} file '{qa_name}'{restarted}")
    return 0
