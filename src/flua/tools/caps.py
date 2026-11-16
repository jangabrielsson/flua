"""caps: the flua capabilities index.

Curated knowledge entries (quirks, idioms, how-tos) with pinning tests —
the agent-facing surface that complements ``--capabilities-json`` (the
machine table in src/flua/capabilities.py). The same content ships in
the wheel and doubles as MCP doc resources, so the tool, the MCP, and
direct file reads can never drift.
"""

from __future__ import annotations

import argparse
import json
import sys

from .. import capabilities

NAME = "caps"
HELP = "the flua capabilities index: curated, pinned knowledge (agents: list/show/search, --json)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--list",
        action="store_true",
        help="every entry: id, title, topic (--json adds pins and verified stamps)",
    )
    parser.add_argument("--show", metavar="ID", help="one entry's full markdown")
    parser.add_argument("--search", metavar="TERMS", help="substring search over the entries")
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable output (agents)",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.list:
        if args.json:
            print(json.dumps(capabilities.load_index(), indent=2, ensure_ascii=False))
            return 0
        for entry in capabilities.entries():
            print(f"{entry.get('id')}  {entry.get('title')} [{entry.get('topic')}]")
        return 0
    if args.show:
        entry = capabilities.get_entry(str(args.show))
        if entry is None:
            print(f"caps: unknown entry {args.show!r} (try --list)", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(entry, indent=2, ensure_ascii=False))
        else:
            print(entry.get("body", ""))
        return 0
    if args.search:
        hits = capabilities.search(str(args.search))
        if args.json:
            print(json.dumps(hits, indent=2, ensure_ascii=False))
        else:
            for hit in hits:
                print(f"{hit['score']}  {hit['id']}  {hit['title']}")
        return 0
    parser.print_help()
    return 1
