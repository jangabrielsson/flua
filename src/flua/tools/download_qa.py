"""downloadQA: download a QA from the HC3 and unpack it into individual Lua files."""

from __future__ import annotations

import argparse
import os

from .common import hc3_engine

NAME = "downloadQA"
HELP = "download a QA from the HC3 and unpack it into individual Lua files"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("qa_id", type=int, help="the QA's device id on the HC3")
    parser.add_argument(
        "-d",
        "--directory",
        metavar="DIR",
        help="target directory (default: the QA's name)",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    # the docs' "empty body" means an empty JSON object — a bodyless POST
    # gets HTTP 400 from the real HC3. Some firmware versions still reject
    # the POST altogether; the deprecated GET is the proven fallback.
    fqa, status = engine.api.dispatch_hc3("POST", f"/quickApp/export/{args.qa_id}", {})
    if status != 200:
        fqa, status = engine.api.dispatch_hc3("GET", f"/quickApp/export/{args.qa_id}", None)
    if status != 200 or not isinstance(fqa, dict):
        parser.error(f"cannot download QA {args.qa_id} (HTTP {status})")
    directory = args.directory or str(fqa.get("name") or f"qa{args.qa_id}")
    os.makedirs(directory, exist_ok=True)
    main_path, err = engine.fqa_to_files(
        fqa, directory, device_id=args.qa_id, strip_header=True
    )
    if err is not None:
        parser.error(f"cannot unpack: {err}")
    print(f"downloaded QA {args.qa_id} ({fqa.get('name')}) to {directory}/ (main: {main_path})")
    return 0
