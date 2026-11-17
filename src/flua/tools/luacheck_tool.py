"""luacheck: run the luacheck linter over a QA's whole file closure.

luacheck itself is NOT bundled — Lua linters ship platform-specific
parsers, so the user installs it (`luarocks install luacheck` /
`brew install luacheck`). What this tool adds is the two parts an agent
must otherwise hand-roll:

- the **closure**: main + `--%%file` extras + `--%%include` defaults,
  with `$lib` bundled libs resolved — the same files that travel in
  the .fqa (reused from the pack pipeline);
- the **globals whitelist**: flua/HC3 globals (fibaro, api, net, ...)
  declared, so luacheck flags REAL undefined variables instead of
  drowning the output in expected-global noise.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NAME = "luacheck"
HELP = "run the luacheck linter over a QA's file closure (needs luacheck on PATH)"

# the flua/HC3 globals a QA may use without definition — pinned by
# tests/test_tools.py::test_luacheck_globals_exist_in_the_runtime, so a
# rename in the runtime cannot silently rot the whitelist
FLUA_GLOBALS = (
    "fibaro",
    "api",
    "net",
    "mqtt",
    "json",
    "QuickApp",
    "QuickAppChild",
    "plugin",
    "hub",
    "_FLUA",
    "setTimeout",
    "clearTimeout",
    "setInterval",
    "clearInterval",
    "_sceneId",
    "sourceTrigger",
    "RefreshStateSubscriber",
    "class",
    "util",
)
# standard Lua globals luacheck's default std may not include for 5.4
LUA_GLOBALS = ("os", "io", "assert", "load", "collectgarbage", "utf8")


def luacheck_config() -> str:
    """The generated .luacheckrc: 5.4 std plus the flua/HC3 whitelist.
    (The CLI --globals form is greedy in luacheck 1.x — it would swallow
    the file paths — so the config file is the transport.)"""
    names = ", ".join(f'"{name}"' for name in (*FLUA_GLOBALS, *LUA_GLOBALS))
    return 'std = "lua54"\nglobals = {' + names + "}\n"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("script", help="the QA's main file (its --%%file closure is linted too)")
    parser.add_argument(
        "--json", action="store_true", help="machine-readable results (agents)"
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    luacheck = shutil.which("luacheck")
    if luacheck is None:
        print(
            "luacheck: the luacheck CLI is not installed (not bundled with flua — "
            "install it: `luarocks install luacheck` or `brew install luacheck`)",
            file=sys.stderr,
        )
        return 2
    from .common import build_fqa

    try:
        fqa, _ = build_fqa(str(args.script), dist=False)
    except (FileNotFoundError, ValueError) as exc:
        print(f"luacheck: {exc}", file=sys.stderr)
        return 2
    files = fqa.get("files") if isinstance(fqa, dict) else None
    if not isinstance(files, list) or not files:
        print(f"luacheck: {args.script} has no files", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="flua-luacheck-") as directory:
        paths: list[str] = []
        for entry in files:
            name = str(entry.get("name") or f"file{len(paths)}.lua")
            content = entry.get("content")
            if not isinstance(content, str):
                continue
            file_name = Path(name).name
            if not Path(name).suffix:
                file_name += ".lua"  # luacheck's format sniffing likes extensions
            path = Path(directory) / file_name
            path.write_text(content, encoding="utf-8")
            paths.append(str(path))
        config = Path(directory) / ".luacheckrc"
        config.write_text(luacheck_config(), encoding="utf-8")
        command = [luacheck, "--config", str(config), "--no-color", *paths]
        result = subprocess.run(command, capture_output=True, text=True)
        output = result.stdout + result.stderr
        if args.json:
            print(json.dumps({"exit": result.returncode, "files": paths, "output": output}))
        else:
            print(output, end="")
            if result.returncode == 0:
                print(f"luacheck: {len(paths)} file(s) clean")
        return result.returncode
