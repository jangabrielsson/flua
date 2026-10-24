#!/usr/bin/env python3
"""Refresh the checked-in device type hierarchy from a real HC3.

The HC3's undocumented ``GET /api/devices/hierarchy`` returns the full
type tree; flua distills it into ``src/flua/devices/hierarchy.json`` (a
child->parent map) so unknown device types can fall back to their nearest
implemented ancestor offline (see ``devices/__init__.py::skeleton_for``).

Usage::

    .venv/bin/python scripts/extract_hierarchy.py
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "flua" / "devices" / "hierarchy.json"

sys.path.insert(0, str(ROOT / "src"))
from flua.environment import EnvChain  # noqa: E402
from flua.hc3 import Hc3Remote  # noqa: E402


def main() -> int:
    chain = EnvChain(ROOT)
    url = chain.get("HC3_URL")
    if not url:
        print("HC3_URL is not set (the .env chain) — nothing to fetch", file=sys.stderr)
        return 1
    remote = Hc3Remote(url, chain.get("HC3_USER"), chain.get("HC3_PASSWORD"), timeout=15)
    data, status = remote.request("GET", "/devices/hierarchy")
    if status != 200 or not isinstance(data, dict):
        print(f"hierarchy fetch failed: HTTP {status}", file=sys.stderr)
        return 1
    parents: dict[str, str] = {}

    def walk(node: dict) -> None:
        for child in node.get("children") or []:
            parents[child["type"]] = node["type"]
            walk(child)

    walk(data)
    info, info_status = remote.request("GET", "/settings/info")
    firmware = (info or {}).get("softVersion") if info_status == 200 else None
    document = {
        "meta": {
            "fetched": datetime.now(UTC).isoformat(),
            "firmware": firmware,
            "note": "distilled from the HC3's undocumented /api/devices/hierarchy — "
            "child->parent map for the offline type fallback",
        },
        "parents": dict(sorted(parents.items())),
    }
    OUT.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} | {len(parents)} types | firmware {firmware}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
