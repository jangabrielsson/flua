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
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NAME = "luacheck"
HELP = (
    "run the luacheck linter over a QA's file closure (needs luacheck on PATH); "
    "a project .luacheckrc next to the main file fully replaces the generated "
    "config — include the runtime globals you use"
)

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
    # the std tables are mutable in QA code: Utils.lua defines
    # table.copy / string.buff and other closure files use them —
    # allow_defined covers globals, not std-table FIELDS
    "table",
    "math",
    "string",
    "os",
)
# standard Lua globals luacheck's default std may not include for 5.4
LUA_GLOBALS = ("io", "assert", "load", "collectgarbage", "utf8")


def _class_names(paths: list[str]) -> list[str]:
    """`class 'Name'` declarations in the closure: allow_defined only sees
    assignments, so class-created globals are appended explicitly."""
    names: list[str] = []
    seen: set[str] = set()
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        for match in re.finditer(r"class\s+['\"]([A-Za-z0-9_]+)['\"]", text):
            name = match.group(1)
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _runtime_globals() -> list[str]:
    """The `__`-prefixed globals the installed runtime defines
    (__assert_type, __fibaro_get_devices, __ternary, __TAG, ...) — derived
    at tool time, so a runtime addition is whitelisted the moment it ships."""
    root = Path(__file__).resolve().parent.parent / "lua"
    names: list[str] = []
    seen: set[str] = set()
    for path in root.rglob("*.lua"):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^(?:function (__[A-Za-z_0-9]+)|(__[A-Za-z_0-9]+)\s*=)", line)
            if match:
                name = match.group(1) or match.group(2)
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
    return names


def _bundled_lib_stems() -> set[str]:
    """The `$`-includable bundled libs (src/flua/lua/lib): flua's own code —
    a QA developer cannot fix their style warnings, so the generated
    config suppresses the style classes for exactly these basenames while
    the undefined-global class (2xx) stays active."""
    root = Path(__file__).resolve().parent.parent / "lua" / "lib"
    return {path.stem for path in root.glob("*.lua")}


def luacheck_config(class_names: list[str] | None = None) -> str:
    """The generated .luacheckrc: 5.4 std, the flua/HC3 whitelist,
    allow_defined (a global assigned in ANY closure file is legal — the
    whole closure lints in one invocation, so cross-file project globals
    stay quiet while truly undefined names still flag), the
    `class 'Name'` globals the closure declares, the `__`-prefixed
    runtime globals, and the std tables made mutable (QA code extends
    table/string/os cross-file). max_line_length is off — brownfield QAs
    do not need a style gate, and a project .luacheckrc can opt back in.
    Bundled libs (qwikchild, eventlib, ...) get their style classes
    (3xx/4xx/6xx) ignored — flua's code, not the QA author's.
    (The CLI --globals form is greedy in luacheck 1.x — it would swallow
    the file paths — so the config file is the transport.)"""
    names = [*FLUA_GLOBALS, *LUA_GLOBALS, *_runtime_globals(), *(class_names or [])]
    body = ", ".join(f'"{name}"' for name in names)
    files = ",\n".join(
        f'  ["{stem}.lua"] = {{ ignore = {{ "212", "3..", "4..", "5..", "6.." }} }}'
        for stem in sorted(_bundled_lib_stems())
    )
    return (
        'std = "lua54"\n'
        "allow_defined = true\n"
        "max_line_length = false\n"
        "globals = {" + body + "}\n"
        "files = {\n" + files + "\n}\n"
    )


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
        names: list[str] = []
        for entry in files:
            name = str(entry.get("name") or f"file{len(names)}.lua")
            content = entry.get("content")
            if not isinstance(content, str):
                continue
            file_name = Path(name).name
            if not Path(name).suffix:
                file_name += ".lua"  # luacheck's format sniffing likes extensions
            (Path(directory) / file_name).write_text(content, encoding="utf-8")
            names.append(file_name)
        # a project .luacheckrc (next to the main file, else the cwd) wins
        # over the generated one — per-project style is the project's call
        project_config = Path(str(args.script)).resolve().parent / ".luacheckrc"
        if not project_config.is_file():
            project_config = Path(".luacheckrc")
        if project_config.is_file():
            config_arg = str(project_config)
        else:
            (Path(directory) / ".luacheckrc").write_text(
                luacheck_config(_class_names([str(Path(directory) / n) for n in names])),
                encoding="utf-8",
            )
            config_arg = ".luacheckrc"
        # cwd is the temp dir and the paths are bare names: luacheck matches
        # its files-patterns against the path AS PASSED, so the bundled-lib
        # basename overrides only work this way
        command = [luacheck, "--config", config_arg, "--no-color", *names]
        result = subprocess.run(command, capture_output=True, text=True, cwd=directory)
        output = result.stdout + result.stderr
        if args.json:
            print(json.dumps({"exit": result.returncode, "files": names, "output": output}))
        else:
            print(output, end="")
            if result.returncode == 0:
                print(f"luacheck: {len(names)} file(s) clean")
        return result.returncode
