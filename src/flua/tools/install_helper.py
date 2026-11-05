"""installHelper: deploy the FluaHelper QA to the HC3 and connect it.

The HC3 serves some of its API only to LOCAL callers (single-key QA
variables, variable writes, ...). The FluaHelper QA runs on the controller
and executes such calls in the local context, reporting back over a
WebSocket to flua's helper server (``--helper-port``; default: a free
OS-assigned port — the on-demand wake advertises the actually-bound one).

This tool uploads the bundled helper (src/flua/lua/FluaHelper_main.lua) as
a new QA and tells it which ws:// URL to dial back to — the address of
THIS machine as the controller sees it (auto-detected via a UDP route
probe, or --host).
"""

from __future__ import annotations

import argparse
import base64
import json
import urllib.parse
from pathlib import Path
from typing import Any

from ..helper import DEFAULT_HELPER_PORT, Hc3Helper, helper_identity
from .common import build_fqa, hc3_engine

NAME = "installHelper"
HELP = "deploy the FluaHelper QA to the HC3 and point it at this machine"


def _helper_source() -> Path:
    return Path(__file__).resolve().parent.parent / "lua" / "FluaHelper_main.lua"


def _bundled_identity() -> tuple[str, str]:
    """(uuid, version) from the bundled helper source — see helper_identity
    (the version bumps on protocol changes and redeploy-requiring fixes;
    this tool compares it against the deployed helper's)."""
    return helper_identity()


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in str(version).split(".") if part.isdigit())


def _filter_helpers(devices: list[dict[str, Any]], uuid: str) -> list[dict[str, Any]]:
    """The deployed helpers among the device list, matched ONLY by the
    quickAppUuid property — never by name (users rename QAs in the web UI)."""
    return [
        device
        for device in devices
        if (device.get("properties") or {}).get("quickAppUuid") == uuid
    ]


def _helper_version(device: dict[str, Any]) -> str:
    return str((device.get("properties") or {}).get("model") or "0.0.0")


def _decide(
    helpers: list[dict[str, Any]], bundled_version: str
) -> tuple[str, dict[str, Any] | None]:
    """What installHelper should do: "install" (no helper deployed),
    "replace" (a deployed helper is OLDER than the bundled one — delete and
    re-upload), or "skip" (same or newer version — keep it, just reconnect).
    Among equal versions the LATEST creation date wins. Returns the decision
    and the best existing helper, if any."""
    if not helpers:
        return "install", None
    best = max(
        helpers,
        key=lambda device: (
            _version_tuple(_helper_version(device)),
            int(device.get("created") or 0),
        ),
    )
    if _version_tuple(_helper_version(best)) < _version_tuple(bundled_version):
        return "replace", best
    return "skip", best


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HELPER_PORT,
        metavar="PORT",
        help=f"the helper server port flua will listen on (default {DEFAULT_HELPER_PORT} "
        "= a free OS-assigned port; pin a fixed one only when you need it)",
    )
    parser.add_argument(
        "--host",
        metavar="IP",
        help="the address the helper should dial (default: this machine's LAN "
        "address as the controller sees it)",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    if engine.hc3 is None:
        parser.error("online mode required (HC3 credentials from the environment chain)")
    uuid, bundled_version = _bundled_identity()

    # the HC3's ?property filter wants the RAW unquoted form —
    # [quickAppUuid,flua-00-01] matches, quoting the value returns empty
    # (verified live on 5.221). The client-side filter stays as the
    # authority either way.
    devices, status = engine.api.dispatch_hc3(
        "GET", f"/devices?property=[quickAppUuid,{uuid}]"
    )
    if status != 200 or not isinstance(devices, list):
        parser.error(f"cannot list HC3 devices (HTTP {status})")
    helpers = _filter_helpers(devices, uuid)
    decision, existing = _decide(helpers, bundled_version)

    helper_id: int
    if decision == "replace":
        for stale in helpers:  # every old copy goes, duplicates included
            _data, del_status = engine.api.dispatch_hc3("DELETE", f"/devices/{stale['id']}")
            if del_status not in (200, 202, 204):
                parser.error(f"cannot remove old FluaHelper {stale['id']} (HTTP {del_status})")
        assert existing is not None
        print(f"removed old FluaHelper (v{_helper_version(existing)})")
    if decision == "skip":
        assert existing is not None
        helper_id = int(existing["id"])
        print(
            f"FluaHelper already installed (v{_helper_version(existing)}) — "
            f"HC3 device id {helper_id}"
        )
        # enforce exactly one helper: any older siblings go
        for stale in helpers:
            if stale["id"] != existing["id"]:
                _data, del_status = engine.api.dispatch_hc3("DELETE", f"/devices/{stale['id']}")
                if del_status not in (200, 202, 204):
                    parser.error(f"cannot remove old FluaHelper {stale['id']} (HTTP {del_status})")
                print(f"removed duplicate FluaHelper {stale['id']}")
    if decision != "skip":
        fqa, _ = build_fqa(str(_helper_source()))
        body: dict[str, Any] = {
            "file": base64.b64encode(
                json.dumps(fqa).encode("utf-8")  # ASCII-escaped: the HC3 reads raw UTF-8 as Latin-1
            ).decode("ascii")
        }
        device, upload_status = engine.api.dispatch_hc3("POST", "/quickApp", body)
        if upload_status not in (200, 201) or not isinstance(device, dict):
            parser.error(f"cannot upload FluaHelper to the HC3 (HTTP {upload_status})")
        helper_id = int(device["id"])
        print(f"uploaded FluaHelper v{bundled_version} — HC3 device id {helper_id}")

    # point the helper (old or new) at THIS machine — the laptop's address
    # may have changed since the last install. With the default port 0 the
    # real port only exists once flua runs, so there is nothing to point at
    # yet: the helper waits idle and flua's on-demand wake carries the
    # actual ws:// URL when it needs the connection.
    if args.port == 0:
        print(
            "helper deployed — it waits idle until flua asks it to connect\n"
            "(online-mode runs advertise their actual port on demand; use\n"
            "--helper-port N on flua to pin a fixed one)"
        )
        return 0
    if args.host:
        host = args.host
    else:
        controller = urllib.parse.urlparse(engine.hc3.base_url).hostname or "127.0.0.1"
        host = Hc3Helper.lan_ip(controller)
    url = f"ws://{host}:{args.port}/"
    _data, connect_status = engine.api.dispatch_hc3(
        "POST", f"/devices/{helper_id}/action/connect", {"args": [url]}
    )
    if connect_status not in (200, 202):
        parser.error(f"cannot connect the helper (HTTP {connect_status})")
    print(f"helper will dial {url} (connect action -> HTTP {connect_status})")
    print(
        "run flua in online mode with the helper server up (--helper-port "
        f"{args.port} if not default) — api.helper calls then route through it"
    )
    return 0
