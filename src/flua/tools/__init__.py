"""The ``flua --tool`` commands.

Each tool is ONE module in this package exporting:

- ``NAME`` — the tool name (as typed after ``--tool``),
- ``HELP`` — a one-line description for the tool's ``--help``,
- ``add_arguments(parser)`` — registers the tool's own arguments,
- ``run(parser, args)`` — executes the tool, returns the exit code.

The registry discovers the modules automatically, so adding a new tool
means adding a new file here.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from typing import Any


def _discover() -> dict[str, Any]:
    tools: dict[str, Any] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        name = getattr(module, "NAME", None)
        if name is not None:
            tools[name] = module
    return tools


_TOOLS = _discover()


def tool_names() -> list[str]:
    return sorted(_TOOLS)


def print_tools() -> None:
    """List the installed tools (name — one-line help)."""
    print("flua tools:")
    for name in tool_names():
        print(f"  {name:<12} {_TOOLS[name].HELP}")
    print()
    print("flua --tool <name> --help   for a tool's own usage")


def run_tool(name: str, argv: list[str]) -> int:
    """Build the tool's parser from its module, parse ``argv``, run it.

    ``name`` of "", "help", "list", "-h" or "--help" lists the installed
    tools (exit 0); unknown names exit 2 with a usage hint.
    """
    if name in ("", "help", "list", "-h", "--help"):
        print_tools()
        return 0
    module = _TOOLS.get(name)
    if module is None:
        print(
            f"flua: unknown tool {name!r} — tools: {', '.join(tool_names())}",
            file=sys.stderr,
        )
        return 2
    parser = argparse.ArgumentParser(prog=f"flua --tool {name}", description=module.HELP)
    module.add_arguments(parser)
    args = parser.parse_args(argv)
    return int(module.run(parser, args))
