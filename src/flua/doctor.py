"""``flua doctor`` — one-command health check for a flua workspace.

Answers "why doesn't it work" in one block: the runtime itself, the
virtualenv, the HC3 credentials (through the same .env chain flua uses —
secrets never printed), HC3 reachability, the LuaLS/VS Code project setup,
the marketplace extension, and the flua-mcp server. Exit code 0 = all
checks ok (problems and skipped checks are reported in the output).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .engine import LuaEngine
from .environment import EnvChain
from .hc3 import Hc3Remote

_EXTENSION_PREFIX = "gsonsoft-development.flua-"
_CREDENTIAL_KEYS = ("HC3_URL", "HC3_USER", "HC3_PASSWORD")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="skip the HC3 reachability check",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable result (one JSON document)",
    )


def _env_source(name: str) -> str:
    if os.environ.get(name) is not None:
        return "environment"
    for path in (Path.cwd() / ".env", Path.home() / ".env"):
        if path.is_file() and name in EnvChain.parse(path):
            return str(path)
    return "unset"


def _check_runtime() -> tuple[bool, str]:
    engine = LuaEngine()
    return True, f"{__version__} ({engine.lua_version()}, Python {sys.version.split()[0]})"


def _check_virtualenv() -> tuple[bool, str]:
    if sys.prefix != sys.base_prefix:
        return True, f"virtualenv at {sys.prefix}"
    return True, f"no virtualenv ({sys.prefix}) — a project venv is recommended"


def _check_credentials() -> tuple[bool, str]:
    chain = EnvChain()
    values = {key: chain.get(key) for key in _CREDENTIAL_KEYS}
    present = [key for key, value in values.items() if value]
    if not present:
        return True, "not configured — offline sim only (set HC3_URL/HC3_USER/"
        "HC3_PASSWORD in the .env chain for online mode)"
    if len(present) != len(_CREDENTIAL_KEYS):
        missing = sorted(set(_CREDENTIAL_KEYS) - set(present))
        return False, f"partially configured — missing {', '.join(missing)}"
    # the URL is not a secret; user/password are never echoed
    return True, f"HC3_URL set (from {_env_source('HC3_URL')})"


def _check_connection(no_network: bool) -> tuple[bool, str]:
    if no_network:
        return True, "skipped (--no-network)"
    url = EnvChain().get("HC3_URL")
    if not url:
        return True, "skipped — no HC3_URL"
    try:
        remote = Hc3Remote(
            url,
            EnvChain().get("HC3_USER"),
            EnvChain().get("HC3_PASSWORD"),
            timeout=5.0,
        )
        data, status = remote.request("GET", "/settings/info")
    except Exception as exc:  # transport surprises: report, never crash
        return False, f"cannot reach {url}: {exc}"
    if status == 200 and isinstance(data, dict):
        name = data.get("hcName") or data.get("serialNumber") or ""
        version = data.get("softVersion") or data.get("version") or ""
        detail = f"{url} reachable"
        if name:
            detail += f" — {name}"
        if version:
            detail += f" (version {version})"
        return True, detail
    if status in (401, 403):
        return False, f"{url} reachable but credentials rejected (HTTP {status})"
    if status == 0:
        return False, f"{url} unreachable (connection failed)"
    return False, f"{url} answered HTTP {status}"


def _check_luals_setup() -> tuple[bool, str]:
    cwd = Path.cwd()
    if (cwd / ".luarc.json").is_file() and (cwd / ".luals").is_dir():
        return True, ".luarc.json + .luals present"
    return False, "no .luarc.json/.luals — run `flua --tool setup` for HC3 autocomplete"


def _check_vscode_setup() -> tuple[bool, str]:
    if (Path.cwd() / ".vscode" / "launch.json").is_file():
        return True, ".vscode/launch.json present"
    return False, "no .vscode/launch.json — run `flua --tool setup` for the run/debug configs"


def _check_extension() -> tuple[bool, str]:
    extensions = Path.home() / ".vscode" / "extensions"
    if extensions.is_dir():
        versions = sorted(
            path.name[len(_EXTENSION_PREFIX):]
            for path in extensions.iterdir()
            if path.is_dir() and path.name.startswith(_EXTENSION_PREFIX)
        )
        if versions:
            return True, f"installed (version {versions[-1]})"
    return False, "not installed — install GsonSoft-development.flua from the marketplace"


def _check_mcp() -> tuple[bool, str]:
    path = shutil.which("flua-mcp")
    if path:
        return True, f"flua-mcp on PATH ({path})"
    return False, "flua-mcp not on PATH (ships with flua; agents use it as an MCP server)"


def _check_project_files() -> tuple[bool, str]:
    cwd = Path.cwd()
    count = len(list(cwd.glob("*.lua"))) + len(list(cwd.glob("*.fqa")))
    detail = f"{count} QA file(s) in {cwd}"
    if (cwd / ".flua-directives").is_file():
        detail += "; .flua-directives overrides active"
    return True, detail


_CHECKS = (
    ("flua", _check_runtime),
    ("virtualenv", _check_virtualenv),
    ("HC3 credentials", _check_credentials),
    ("HC3 connection", _check_connection),
    ("LuaLS setup", _check_luals_setup),
    ("VS Code run/debug", _check_vscode_setup),
    ("VS Code extension", _check_extension),
    ("flua-mcp", _check_mcp),
    ("project files", _check_project_files),
)


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    checks = []
    for name, check in _CHECKS:
        if name == "HC3 connection":
            ok, detail = check(args.no_network)
        else:
            ok, detail = check()
        checks.append({"name": name, "ok": ok, "detail": detail})
    if args.json:
        print(json.dumps({"ok": all(c["ok"] for c in checks), "checks": checks}))
        return 0 if all(c["ok"] for c in checks) else 1
    print("flua doctor")
    for check in checks:
        mark = "✓" if check["ok"] else "✗"
        print(f"  {mark} {check['name']:<17} {check['detail']}")
    problems = sum(1 for check in checks if not check["ok"])
    print(f"flua doctor: {len(checks) - problems} ok, {problems} problem(s)")
    return 0 if not problems else 1
