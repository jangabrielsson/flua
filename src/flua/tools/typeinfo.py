"""typeinfo: a type's or interface's properties and actions (the QA contract).

The implementation contract for a device type or interface: what
properties the device gets (with types, defaults, enums), what actions it
answers (the QuickApp methods a QA should implement), and where each entry
comes from — the type's own declaration, a base type, or an interface.
The `--json` shape is the machine contract agents and the extension read.
"""

from __future__ import annotations

import argparse
import json
import sys
from difflib import get_close_matches

from ..devices import type_info, type_schemas

NAME = "typeinfo"
HELP = "a type's or interface's properties and actions (the QA implementation contract)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "name", nargs="?", help="a device type or interface name (omit to list both)"
    )
    parser.add_argument(
        "--json", action="store_true", help="the machine-readable shape (for agents)"
    )


def _all_names() -> list[str]:
    schemas = type_schemas()
    return sorted([*schemas["types"], *schemas["interfaces"]])


def _human(info: dict) -> str:
    lines: list[str] = []
    if info["kind"] == "type":
        base = f"  (base: {info['baseType']})" if info.get("baseType") else ""
        lines.append(f"{info['name']}{base}")
        if info["interfaces"]:
            lines.append("interfaces: " + ", ".join(info["interfaces"]))
    else:
        lines.append(f"{info['name']} (interface) — what adding it contributes:")
    lines.append("")
    if info["properties"]:
        lines.append("properties:")
        for name, spec in sorted(info["properties"].items()):
            bits = [spec.get("type", "string")]
            if "default" in spec:
                default = spec["default"]
                if isinstance(default, list) and len(default) > 6:
                    bits.append(f"default [{len(default)} items]")
                else:
                    bits.append(f"default {default!r}")
            enum = spec.get("enum")
            if enum:
                bits.append(f"enum: {len(enum)} values")
            lines.append(f"  {name} ({', '.join(bits)})  [{spec['from']}]")
    else:
        lines.append("properties: (none)")
    lines.append("")
    if info["kind"] == "type":
        lines.append("actions (implement as QuickApp:<name> methods):")
    else:
        lines.append("actions:")
    if info["actions"]:
        for name, spec in sorted(info["actions"].items()):
            args = ""
            if spec.get("args"):
                args = "(" + ",".join(f"{a['name']}:{a['type']}" for a in spec["args"]) + ")"
            lines.append(f"  {name}{args}  [{spec['from']}]")
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def run(_parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if not args.name:
        schemas = type_schemas()
        for name in sorted(schemas["types"]):
            print(f"type      {name}")
        for name in sorted(schemas["interfaces"]):
            print(f"interface {name}")
        return 0
    info = type_info(args.name)
    if info is None:
        close = get_close_matches(args.name, _all_names(), n=3, cutoff=0.5)
        hint = f" — did you mean {', '.join(repr(n) for n in close)}?" if close else ""
        print(f"unknown type or interface: {args.name!r}{hint}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(info, ensure_ascii=False))
        return 0
    print(_human(info))
    return 0
