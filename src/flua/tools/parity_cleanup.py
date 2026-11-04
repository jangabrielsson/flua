"""``flua --tool parityCleanup`` — remove flua-p-* parity artifacts left on
an HC3 by a crashed parityCapture.

The capture tears its own artifacts down LIFO; this is the safety net for
interrupted runs. ``--list`` (default) scans /devices, /globalVariables and
/customEvents for names starting with the prefix and prints them grouped;
``--yes`` deletes them. The prefix guard accepts only ``flua-p-*`` so a
typo cannot target real devices.
"""

from __future__ import annotations

import argparse
from typing import Any

from .common import hc3_engine

NAME = "parityCleanup"
HELP = "list and remove flua-p-* parity artifacts left on an HC3"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--prefix", default="flua-p-", help="artifact name prefix (default: flua-p-)"
    )
    parser.add_argument(
        "--yes", action="store_true", help="delete the listed artifacts"
    )


def check_prefix(prefix: str) -> str:
    """Validate and return the prefix — ValueError when it could target
    real devices (anything outside the parity namespace)."""
    if not prefix.startswith("flua-p-"):
        raise ValueError(
            f"refusing: --prefix must start with 'flua-p-' (got {prefix!r})"
        )
    return prefix


def scan_artifacts(client: Any, prefix: str) -> dict[str, list[dict]]:
    """Artifacts whose name starts with the prefix, grouped by kind."""
    devices, _status = client.request("GET", "/devices")
    globals_, _status = client.request("GET", "/globalVariables")
    events, _status = client.request("GET", "/customEvents")

    def _match(entries: Any) -> list[dict]:
        if not isinstance(entries, list):
            return []
        return [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and str(entry.get("name", "")).startswith(prefix)
        ]

    return {
        "devices": _match(devices),
        "globalVariables": _match(globals_),
        "customEvents": _match(events),
    }


def delete_artifacts(client: Any, found: dict[str, list[dict]]) -> list[str]:
    """Delete every listed artifact; one report line each. 404 = already
    gone, counted as removed."""
    lines: list[str] = []
    for kind, path_key in (
        ("devices", "id"),
        ("globalVariables", "name"),
        ("customEvents", "name"),
    ):
        for entry in found[kind]:
            ref = entry.get(path_key)
            if ref is None:
                lines.append(f"{kind} ?: no {path_key}, skipped")
                continue
            path = f"/devices/{ref}" if kind == "devices" else f"/{kind}/{ref}"
            _data, status = client.request("DELETE", path)
            gone = " (already gone)" if status == 404 else ""
            lines.append(f"{kind} {ref}: HTTP {status}{gone}")
    return lines


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    try:
        prefix = check_prefix(args.prefix)
    except ValueError as exc:
        parser.error(str(exc))
    engine = hc3_engine(parser)
    if engine.hc3 is None:
        parser.error("online mode required (HC3 credentials from the environment chain)")

    found = scan_artifacts(engine.hc3, prefix)
    total = sum(len(entries) for entries in found.values())
    print(f"parity artifacts matching {prefix!r}: {total}")
    for kind in ("devices", "globalVariables", "customEvents"):
        for entry in found[kind]:
            print(f"  {kind[:-1] if kind.endswith('s') else kind}: "
                  f"{entry.get('name')} (id {entry.get('id')})")
    if not total:
        return 0
    if args.yes:
        print("\ndeleting:")
        for line in delete_artifacts(engine.hc3, found):
            print(f"  {line}")
        return 0
    print("\nrun with --yes to delete these")
    return 0
