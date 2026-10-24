"""pack: package a QA project into a .fqa file on disk.

The tool form of ``flua export``: same machinery as uploadQA (the QA's
--%%file extras travel along), but the package stays local.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config import expand_includes, parse_annotations
from .common import build_fqa, default_fqa_output

NAME = "pack"
HELP = "package a QA project (main file + --%%file extras) into a .fqa file on disk"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("script", help="the QA main file")
    parser.add_argument(
        "-o",
        "--output",
        help="the .fqa output path (default: <QA name>.fqa — the --%%name, "
        "or MyQA.fqa without one — next to the main file)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite an existing file",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    script = Path(args.script)
    try:
        source = script.read_text(encoding="utf-8")
        annotations = expand_includes(
            parse_annotations(source, warn_unknown=False), script.parent
        )
    except OSError as exc:
        parser.error(f"cannot open {args.script}: {exc}")
    except ValueError as exc:
        parser.error(f"error in {args.script}: {exc}")
    try:
        fqa, _ = build_fqa(args.script, dist=True)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    output = Path(args.output) if args.output else default_fqa_output(script, annotations)
    if output.exists() and not args.force:
        parser.error(f"{output} exists — pass --force to overwrite")
    output.write_text(json.dumps(fqa, indent=2), encoding="utf-8")
    print(f"packed {fqa['name']} ({len(fqa.get('files') or [])} files) to {output}")
    return 0
