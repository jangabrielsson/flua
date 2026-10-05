"""downloadFQA: download a QA from the HC3 as a .fqa file.

The package counterpart of downloadQA (which downloads as an unpacked
project): the HC3's export endpoint returns the .fqa JSON, saved to disk.
Offline it exports the emulated QA from the sim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..engine import sanitize_filename
from .common import hc3_engine

NAME = "downloadFQA"
HELP = "download a QA from the HC3 as a .fqa file"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", type=int, help="the QA's HC3 device id")
    parser.add_argument(
        "-o",
        "--output",
        help="the .fqa output path (default: <QA-name>.fqa in the current directory)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite an existing file",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    fqa, status = engine.api.dispatch_hc3("POST", f"/quickApp/{args.id}/export", None)
    if status != 200 or not isinstance(fqa, dict):
        parser.error(f"cannot export QA {args.id} (HTTP {status})")
    output = (
        Path(args.output)
        if args.output
        else Path(sanitize_filename(str(fqa.get("name") or f"qa{args.id}")) + ".fqa")
    )
    if output.exists() and not args.force:
        parser.error(f"{output} exists — pass --force to overwrite")
    output.write_text(json.dumps(fqa, indent=2), encoding="utf-8")
    print(f"downloaded {fqa.get('name')} (id {args.id}) to {output}")
    return 0
