"""``flua --tool state`` — inspect simulator state: dump, alias scan, tree
invariant (the agent-troubleshooting proposal's P3/P6).

The default dump summarizes the persistent state of a seed/db/recording
file. ``--aliases`` reports every object reachable from more than one path
(the shape of the updateView aliasing bug: one list stored into two state
paths). ``--verify-tree`` exits non-zero when the state contains shared
references or cycles — the "state is a JSON tree" invariant.

A db file cannot express aliasing (JSON has no identity), so the alias
scan and the invariant are also importable functions: agents and tests
point them at a live engine's state —
``scan_tree(engine.api.state).get("aliases")``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..api.state import SimState

NAME = "state"
HELP = "inspect simulator state from a seed/db file (dump, alias scan, tree check)"

# the transient feeds are streams, not the persistent tree — never scanned
_SKIP = (
    "events",
    "changes",
    "debug_messages",
    "system_events",
    "_refresh_seq",
    "_debug_seq",
    "_db_qa_state",
)

_DUMP_PROPERTIES = (
    "value",
    "state",
    "dead",
    "batteryLevel",
    "power",
    "energy",
    "temperature",
    "sunriseHour",
    "sunsetHour",
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        metavar="FILE",
        help="seed/db/recording JSON to load (default: the empty sim)",
    )
    parser.add_argument(
        "--aliases",
        action="store_true",
        help="report every object reachable from more than one state path",
    )
    parser.add_argument(
        "--verify-tree",
        action="store_true",
        help="exit non-zero if the state contains shared references or cycles",
    )


def load_state(path: str | None, parser: argparse.ArgumentParser) -> SimState:
    if path is None:
        return SimState()
    try:
        seed = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        parser.error(f"cannot read {path}: {exc}")
    except ValueError as exc:
        parser.error(f"invalid JSON in {path}: {exc}")
    if not isinstance(seed, dict):
        parser.error("state file must contain a JSON object")
    return SimState(seed)


def dump(state: SimState) -> dict[str, Any]:
    """A compact, JSON-safe summary of the persistent state."""
    devices = []
    for device in state.devices.values():
        properties = device.get("properties") or {}
        summary = {
            key: properties[key] for key in _DUMP_PROPERTIES if key in properties
        }
        devices.append(
            {
                "id": device.get("id"),
                "name": device.get("name"),
                "type": device.get("type"),
                "parentId": device.get("parentId"),
                **({"properties": summary} if summary else {}),
            }
        )
    variables = {
        str(qa_id): dict(vars_) for qa_id, vars_ in state.plugin_variables.items()
    }
    return {"devices": devices, "pluginVariables": variables}


def scan_tree(state: SimState) -> dict[str, list[Any]]:
    """Identity-scan the persistent state containers.

    Returns {"aliases": [{"paths": [...], "repr": ...}], "cycles": [path]}.
    A path is a dotted/indexed string like
    ``devices[10].properties.uiView[0].components[1].options``. Nested paths
    (one a prefix of the other) count as cycles, not aliases."""
    seen: dict[int, list[str]] = {}
    in_progress: set[int] = set()
    cycles: list[str] = []

    def walk(obj: Any, path: str) -> None:
        if not isinstance(obj, (dict, list)):
            return
        identity = id(obj)
        if identity in in_progress:
            cycles.append(path)
            return
        seen.setdefault(identity, []).append(path)
        in_progress.add(identity)
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in _SKIP:
                    continue
                segment = f"[{key}]" if isinstance(key, int) else f".{key}"
                walk(value, path + segment)
        else:
            for index, value in enumerate(obj):
                walk(value, f"{path}[{index}]")
        in_progress.discard(identity)

    for name in (
        "devices",
        "plugin_variables",
        "rooms",
        "sections",
        "climate_zones",
        "family_locations",
        "scenes",
        "global_variables",
        "alarms",
        "profiles",
        "location",
    ):
        walk(getattr(state, name, None), name)

    aliases = []
    for identity, paths in seen.items():

        def covered(path: str, all_paths: list[str] = paths) -> bool:
            # the object appears nested within itself along another path:
            # that's the cycle case, reported separately
            return any(
                other != path
                and (path.startswith(other + ".") or path.startswith(other + "["))
                for other in all_paths
            )

        distinct = [path for path in paths if not covered(path)]
        if len(distinct) >= 2:
            aliases.append({"paths": distinct, "object": identity})
    return {"aliases": aliases, "cycles": cycles}


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    state = load_state(args.db, parser)
    if args.aliases:
        report = scan_tree(state)
        if not report["aliases"] and not report["cycles"]:
            print("no aliases, no cycles — the state is a clean JSON tree")
            return 0
        for entry in report["aliases"]:
            print("aliased object:")
            for path in entry["paths"]:
                print(f"  {path}")
        for path in report["cycles"]:
            print(f"cycle: {path}")
        return 0
    if args.verify_tree:
        report = scan_tree(state)
        if report["aliases"] or report["cycles"]:
            for entry in report["aliases"]:
                print("shared reference: " + " also ".join(entry["paths"]))
            for path in report["cycles"]:
                print(f"cycle: {path}")
            return 1
        print("ok — no shared references, no cycles")
        return 0
    print(json.dumps(dump(state), indent=1))
    return 0
