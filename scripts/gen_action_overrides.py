#!/usr/bin/env python3
"""Generate/merge src/flua/devices/action_overrides.json.

The starter list: every distinct action and the argument info the schema
has (argc + args). Hand-edit the file to add argument names/types for the
actions you know — common actions (setValue, setArmed, ...) are the
usual suspects. Merging never overwrites existing entries, so
regeneration preserves hand edits; `typeinfo` consults the file when it
renders action signatures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "src" / "flua" / "devices" / "type_schemas.json"
OVERRIDES_PATH = ROOT / "src" / "flua" / "devices" / "action_overrides.json"


def main() -> int:
    schemas = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}
    for entry in list(schemas["types"].values()) + list(schemas["interfaces"].values()):
        for name, spec in (entry.get("actions") or {}).items():
            if name not in found:
                found[name] = {
                    "argc": spec.get("argc", 0),
                    **({"args": spec["args"]} if spec.get("args") else {}),
                }
    existing: dict[str, dict] = {}
    if OVERRIDES_PATH.is_file():
        existing = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    added = 0
    for name, spec in found.items():
        if name not in existing:
            existing[name] = spec
            added += 1
    merged = dict(sorted(existing.items()))
    OVERRIDES_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        f"action_overrides.json: {len(merged)} actions "
        f"({added} new, {len(found) - added} hand-kept)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
