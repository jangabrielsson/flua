"""hub: named HC3 profiles — switch the .env chain between controllers.

The .env chain (process env > project .env > ~/.env) is flua's controller
selection; this tool gives each controller a name and one-command switching
(design: docs/notes/notes-hub-profiles.md):

    flua --tool hub add home http://192.168.1.20 admin   # prompts for the password
    flua --tool hub list --json                          # names/urls/serials, never passwords
    flua --tool hub switch home                          # ~/.env (the global default)
    flua --tool hub switch home --project                # this project's .env (a pin)
    flua --tool hub remove home

Profiles live in ~/.flua/hubs.json (mode 0600, the same plaintext-on-disk
posture as .env). The tool never prints a password, and `add` also
captures the hub's serial (a reachability check) so the extension's picker
can show it without a network call.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
from typing import Any

from ..environment import EnvChain
from ..hc3 import Hc3Remote

NAME = "hub"
HELP = "named HC3 profiles: add/list/switch/remove controllers for the .env chain"

_CREDENTIAL_KEYS = ("HC3_URL", "HC3_USER", "HC3_PASSWORD")


def _profiles_path() -> Path:
    return Path.home() / ".flua" / "hubs.json"


def _load_profiles(parser: argparse.ArgumentParser) -> dict[str, dict[str, Any]]:
    path = _profiles_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(f"cannot read {path}: {exc}")
    return raw if isinstance(raw, dict) else {}


def _save_profiles(profiles: dict[str, dict[str, Any]], parser: argparse.ArgumentParser) -> None:
    path = _profiles_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")
        path.chmod(0o600)
    except OSError as exc:
        parser.error(f"cannot write {path}: {exc}")


def _serial(url: str, user: str, password: str) -> str | None:
    """The hub's serial (hcName) — also the add-time reachability check.
    Never raises: an unreachable controller still gets a profile (serial
    stays empty), like doctor's reachability posture."""
    try:
        data, status = Hc3Remote(url, user, password, timeout=5.0).request("GET", "/settings/info")
        if status == 200 and isinstance(data, dict):
            return str(data.get("hcName") or data.get("serialNumber") or "") or None
    except Exception:
        pass
    return None


def _prompt_password() -> str:
    # scripting/CI (and the tool tests): FLUA_HUB_PASSWORD skips the prompt.
    # getpass reads /dev/tty when one exists, so stdin redirection alone is
    # never enough to feed it — the env var is the non-interactive contract.
    from_env = os.environ.get("FLUA_HUB_PASSWORD")
    if from_env:
        return from_env
    try:
        return getpass.getpass("HC3 password: ")
    except EOFError:
        return ""


def _cmd_add(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    profiles = _load_profiles(parser)
    if args.name in profiles and not args.force:
        parser.error(f"profile {args.name!r} exists — pass --force to replace it")
    password = _prompt_password()
    if not password:
        parser.error("no password given")
    serial = _serial(args.url, args.user, password)
    profiles[args.name] = {"url": args.url, "user": args.user, "password": password}
    if serial:
        profiles[args.name]["serial"] = serial
    _save_profiles(profiles, parser)
    print(f"added hub {args.name!r} ({args.url}{f', {serial}' if serial else ''})")
    return 0


def _cmd_list(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    profiles = _load_profiles(parser)
    active_url = EnvChain().get("HC3_URL")
    if args.json:
        # never the passwords — this is the extension/agent contract
        public = {
            name: {
                key: value
                for key, value in profile.items()
                if key != "password"
            }
            | {"active": active_url is not None and profile.get("url") == active_url}
            for name, profile in profiles.items()
        }
        print(json.dumps(public, ensure_ascii=False))
        return 0
    if not profiles:
        print("no hubs — `flua --tool hub add <name> <url> <user>` to add one")
        return 0
    for name in sorted(profiles):
        profile = profiles[name]
        serial = profile.get("serial") or "?"
        mark = " *" if active_url is not None and profile.get("url") == active_url else ""
        print(f"  {name:<16} {profile['url']}  ({serial}, user {profile['user']}){mark}")
    return 0


def _rewrite_env(path: Path, values: dict[str, str]) -> None:
    """Replace the HC3 keys in an .env file, preserving every other line."""
    kept = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        key = line.split("=", 1)[0].strip()
        if key not in _CREDENTIAL_KEYS:
            kept.append(line)
    for key in _CREDENTIAL_KEYS:
        kept.append(f"{key}={values[key]}")
    path.write_text("\n".join(kept).rstrip("\n") + "\n", encoding="utf-8")


def _cmd_switch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    profiles = _load_profiles(parser)
    profile = profiles.get(args.name)
    if profile is None:
        parser.error(f"unknown hub {args.name!r} — `flua --tool hub list` shows the profiles")
    values = {
        "HC3_URL": str(profile["url"]),
        "HC3_USER": str(profile["user"]),
        "HC3_PASSWORD": str(profile["password"]),
    }
    target = Path.cwd() / ".env" if args.project else Path.home() / ".env"
    _rewrite_env(target, values)
    scope = "this project" if args.project else "the global default"
    print(f"switched {scope} to {args.name!r} ({profile['url']}) — wrote {target}")
    return 0


def _cmd_remove(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    profiles = _load_profiles(parser)
    if args.name not in profiles:
        parser.error(f"unknown hub {args.name!r}")
    del profiles[args.name]
    _save_profiles(profiles, parser)
    print(f"removed hub {args.name!r} (any .env pointing at it stays — switch explicitly)")
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)
    p_add = sub.add_parser("add", help="add (or replace with -f) a hub profile")
    p_add.add_argument("name")
    p_add.add_argument("url")
    p_add.add_argument("user")
    p_add.add_argument("-f", "--force", action="store_true", help="replace an existing name")
    p_list = sub.add_parser("list", help="list the profiles (never the passwords)")
    p_list.add_argument("--json", action="store_true", help="machine-readable list")
    p_switch = sub.add_parser("switch", help="write a profile into the .env chain")
    p_switch.add_argument("name")
    p_switch.add_argument(
        "--project",
        action="store_true",
        help="write the project .env (a per-folder pin) instead of ~/.env",
    )
    p_remove = sub.add_parser("remove", help="delete a profile")
    p_remove.add_argument("name")


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    handlers = {
        "add": _cmd_add,
        "list": _cmd_list,
        "switch": _cmd_switch,
        "remove": _cmd_remove,
    }
    return handlers[args.command](parser, args)
