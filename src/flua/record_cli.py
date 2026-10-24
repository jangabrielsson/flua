"""``flua record`` — capture a real house session into a replayable file.

The HC3's event feed is /refreshStates (the same stream flua's online mode
consumes): the recorder snapshots the full device list once, then polls the
feed and appends every DevicePropertyUpdatedEvent as a relative-time delta.
The result seeds the offline sim (``flua --replay house.json qa.lua``) and
fires the same property changes on the virtual timeline — the QA under test
experiences the real house's behavior, fast or instant.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from .engine import LuaEngine


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default="house.json",
        help="the recording to write (default: house.json)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="how long to record (default 60; Ctrl-C stops early and saves)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="refreshStates poll interval (default 1s)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite an existing file",
    )


async def _record(args: argparse.Namespace, output: Path) -> tuple[dict, str | None]:
    """Capture the session; returns (document, error)."""
    engine = LuaEngine(api_mode="remote")  # raises without HC3 credentials
    devices, status = engine.api.dispatch_hc3("GET", "/devices", None)
    if status != 200 or not isinstance(devices, list):
        return {}, f"cannot read the device list (HTTP {status})"
    info, info_status = engine.api.dispatch_hc3("GET", "/settings/info", None)
    controller = (
        (info or {}).get("hcName") or (info or {}).get("serialNumber")
        if info_status == 200
        else None
    )
    document: dict = {
        "version": 1,
        "meta": {
            "capturedAt": datetime.now(UTC).isoformat(),
            "controller": controller,
        },
        "devices": devices,
        "events": [],
    }
    last: dict[tuple, object] = {}
    for device in devices:
        for key, value in (device.get("properties") or {}).items():
            last[(device.get("id"), key)] = value
    start = time.monotonic()
    try:
        while time.monotonic() - start < args.duration:
            await asyncio.sleep(args.interval)
            data, feed_status = engine.api.dispatch_hc3("GET", "/refreshStates", None)
            if feed_status != 200 or not isinstance(data, dict):
                continue
            for event in data.get("events") or []:
                if not isinstance(event, dict):
                    continue
                if event.get("type") != "DevicePropertyUpdatedEvent":
                    continue
                detail = event.get("data") or {}
                device_id = detail.get("id")
                property_name = detail.get("property")
                new_value = detail.get("newValue")
                if device_id is None or property_name is None:
                    continue
                key = (device_id, property_name)
                if last.get(key) == new_value:
                    continue  # no real change — the HC3 re-sends the last state
                last[key] = new_value
                document["events"].append(
                    {
                        "t": round(time.monotonic() - start, 2),
                        "deviceId": device_id,
                        "property": property_name,
                        "newValue": new_value,
                    }
                )
    except KeyboardInterrupt:
        pass
    return document, None


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    output = Path(args.output)
    if output.exists() and not args.force:
        parser.error(f"{output} exists — pass --force to overwrite")
    document, error = asyncio.run(_record(args, output))
    if error:
        parser.error(error)
    output.write_text(json.dumps(document, indent=2), encoding="utf-8")
    device_count = len(document.get("devices") or [])
    print(f"recorded {len(document['events'])} events from {device_count} devices to {output}")
    return 0
