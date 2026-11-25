"""api: make an HC3 API call and print the result.

Probe the controller without curling credentials around: the tool uses the
.env chain (hub profiles) like every other tool, so `flua --tool api
/plugins/getView?id=4599` is the whole command. The response prints as
pretty JSON (or raw text when the body isn't JSON) with the HTTP status on
stderr; `--json` emits one compact line `{"res": ..., "code": ...}` for
agents/scripts. Offline (no credentials) the call lands in the simulated
HC3, like every dispatch — useful for probing the sim's state.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .common import hc3_engine

NAME = "api"
HELP = "make an HC3 API call and print the result (pretty JSON + HTTP status)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "path",
        help="the API path, e.g. /devices/123 or /plugins/getView?id=123 "
        "(quote paths with ? — the shell would glob them)",
    )
    parser.add_argument(
        "-X",
        "--method",
        default="GET",
        metavar="METHOD",
        help="the HTTP method (default GET)",
    )
    parser.add_argument(
        "-d",
        "--data",
        default=None,
        metavar="JSON",
        help="a JSON request body (POST/PUT)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine output: one line {\"res\": ..., \"code\": ...}",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    path = args.path if args.path.startswith("/") else "/" + args.path
    body: Any = None
    if args.data is not None:
        try:
            body = json.loads(args.data)
        except ValueError as exc:
            parser.error(f"--data is not valid JSON: {exc}")
    data, status = engine.api.dispatch_hc3(args.method.upper(), path, body)
    if args.json:
        print(json.dumps({"res": data, "code": status}, ensure_ascii=False))
        return 0 if status < 400 else 1
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif data is not None and data != "":
        print(data)
    print(f"HTTP {status}", file=sys.stderr)
    return 0 if status < 400 else 1
