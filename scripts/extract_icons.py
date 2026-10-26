#!/usr/bin/env python3
"""Refresh the checked-in icon catalog from a real HC3.

The HC3's ``GET /api/icons`` returns the controller's icon library —
device icon sets (id, iconSetName, deviceType, fileExtension) plus the
room and scene icons. flua stores the raw payload in
``src/flua/devices/icons.json`` so the sim can serve the same catalog
offline (QA ``deviceIcon`` ids stay aligned with the real controller) and
lint unknown icon ids.

The payload is kept verbatim: the sim serves icons in the HC3's shape, so
the reference must be the shape the HC3 actually returns.

Usage::

    .venv/bin/python scripts/extract_icons.py
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "flua" / "devices" / "icons.json"

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
    data, status = remote.request("GET", "/icons")
    if status != 200:
        print(f"icon catalog fetch failed: HTTP {status}", file=sys.stderr)
        return 1
    info, info_status = remote.request("GET", "/settings/info")
    firmware = (info or {}).get("softVersion") if info_status == 200 else None
    document = {
        "meta": {
            "fetched": datetime.now(UTC).isoformat(),
            "firmware": firmware,
            "note": "verbatim GET /api/icons payload from the HC3 — the controller's "
            "icon library (device/room/scene icon sets), served offline by the sim",
        },
        "data": data,
    }
    OUT.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")

    def count(section: str) -> int:
        items = data.get(section) if isinstance(data, dict) else None
        return len(items) if isinstance(items, list) else 0

    device_count = count("device")
    print(
        f"wrote {OUT} | icons: {device_count} device sets, "
        f"{count('room')} room, {count('scene')} scene | firmware {firmware}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
