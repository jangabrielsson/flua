"""updateQA: update an existing QA on the HC3 from an unpacked project."""

from __future__ import annotations

import argparse

from .common import build_fqa, fqa_files, hc3_engine

NAME = "updateQA"
HELP = "update an existing QA on the HC3 from an unpacked project (all files at once)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("qa_id", type=int, help="the QA's device id on the HC3")
    parser.add_argument("script", help="the QA main file")


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    try:
        fqa, _ = build_fqa(args.script)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    files = fqa_files(fqa)
    _data, status = engine.api.dispatch_hc3("PUT", f"/quickApp/{args.qa_id}/files", files)
    if status not in (200, 204):
        parser.error(f"cannot update QA {args.qa_id} (HTTP {status})")
    print(f"updated QA {args.qa_id} ({len(files)} files)")
    return 0
