"""unpack: unpack a local .fqa file into a flua project.

The tool form of ``flua unpack``: the package's directives come back as a
--%% header, its files as one file per QA file — a normal flua project.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ..engine import LuaEngine

NAME = "unpack"
HELP = "unpack a .fqa file into a flua project (main.lua + one file per QA file)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("package", help="the .fqa file (a local HC3 export)")
    parser.add_argument(
        "-d",
        "--directory",
        help="the project directory (default: the QA's name, sanitized)",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    path = Path(args.package)
    if not path.exists():
        parser.error(f"cannot open {args.package}: no such file")
    try:
        fqa = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        parser.error(f"invalid fqa JSON: {exc}")
    if not isinstance(fqa, dict):
        parser.error("fqa file must contain a JSON object")
    directory = args.directory or Path(str(fqa.get("name") or "quickapp")).name
    os.makedirs(directory, exist_ok=True)
    main_path, err = LuaEngine().fqa_to_files(fqa, directory)
    if err is not None:
        parser.error(f"cannot unpack: {err}")
    print(f"unpacked to {directory}/ (main: {main_path})")
    return 0
