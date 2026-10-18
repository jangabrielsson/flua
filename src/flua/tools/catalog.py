"""catalog: list the device types the sim supports (devices.json).

The HC3 device catalog the sim builds skeletons from — the answer to
"unknown device type" errors and the reference for ``--%%type``. One type
per line; ``--json`` gives a JSON array. Agents prefer the JSON shape.
"""

from __future__ import annotations

import argparse
import json

from ..devices import catalog_types

NAME = "catalog"
HELP = "list the device types the sim supports (the --%%type catalog)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", help="a JSON array of types instead of lines"
    )


def run(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    types = catalog_types()
    if args.json:
        print(json.dumps(types, ensure_ascii=False))
    else:
        for device_type in types:
            print(device_type)
    return 0
