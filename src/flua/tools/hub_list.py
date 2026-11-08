"""hubList: the hub's identity and its QuickApps as one JSON document.

The data source for the VS Code hub browser (and the same surface an agent
can call): hub name/model/firmware/reachability from /settings/info (the
same checks `flua doctor` performs) plus the QuickApp list from /devices
filtered by the quickApp interface, rooms resolved by name. QAs are keyed
by id — HC3 names are not unique.

Always prints one JSON document on stdout; the shape is the contract:

    {"hub": {"name": ..., "model": ..., "firmware": ..., "url": ...,
             "reachable": true},
     "qas": [{"id": 57, "name": "Heating",
              "type": "com.fibaro.deviceController", "room": "Living room"}]}
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from ..environment import EnvChain
from ..hc3 import Hc3Remote

NAME = "hubList"
HELP = "list a hub's QuickApps and hub info as one JSON document"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="hub request timeout (default 5s)",
    )


def _hub_info(remote: Hc3Remote, url: str, timeout: float) -> tuple[dict[str, Any], bool]:
    info: dict[str, Any] = {"url": url, "reachable": False}
    try:
        data, status = remote.request("GET", "/settings/info")
    except Exception as exc:  # transport surprises: report, never crash
        info["error"] = f"cannot reach {url}: {exc}"
        return info, False
    if status == 200 and isinstance(data, dict):
        info["reachable"] = True
        info["name"] = data.get("hcName") or data.get("serialNumber") or ""
        info["model"] = data.get("model") or ""
        info["firmware"] = data.get("softVersion") or data.get("version") or ""
        return info, True
    if status in (401, 403):
        info["error"] = f"credentials rejected (HTTP {status})"
    elif status == 0:
        info["error"] = "unreachable (connection failed)"
    else:
        info["error"] = f"the hub answered HTTP {status}"
    return info, False


def _rooms_by_id(remote: Hc3Remote) -> dict[int, str]:
    try:
        rooms, status = remote.request("GET", "/rooms")
    except Exception:
        return {}
    if status != 200 or not isinstance(rooms, list):
        return {}
    out: dict[int, str] = {}
    for room in rooms:
        if isinstance(room, dict) and room.get("id") is not None and room.get("name"):
            out[int(room["id"])] = str(room["name"])
    return out


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    chain = EnvChain()
    url = chain.get("HC3_URL")
    if not url:
        parser.error(
            "online mode requires HC3_URL (or HC3_HOST) in the environment — "
            "set HC3_URL/HC3_USER/HC3_PASSWORD in the .env chain"
        )
    remote = Hc3Remote(url, chain.get("HC3_USER"), chain.get("HC3_PASSWORD"), timeout=args.timeout)
    hub, ok = _hub_info(remote, url, args.timeout)
    qas: list[dict[str, Any]] = []
    if ok:
        rooms = _rooms_by_id(remote)
        try:
            devices, status = remote.request("GET", "/devices")
        except Exception as exc:
            parser.error(f"cannot list devices: {exc}")
        if status == 200 and isinstance(devices, list):
            for dev in devices:
                if not isinstance(dev, dict) or "quickApp" not in (dev.get("interfaces") or []):
                    continue
                qa = {
                    "id": dev.get("id"),
                    "name": dev.get("name"),
                    "type": dev.get("type"),
                    "room": rooms.get(dev.get("roomID")) if dev.get("roomID") is not None else None,
                }
                qas.append(qa)
            qas.sort(key=lambda qa: (qa["id"] is None, qa["id"] or 0))
        else:
            hub["error"] = f"cannot list QuickApps (HTTP {status})"
            ok = False
    print(json.dumps({"hub": hub, "qas": qas}))
    return 0 if ok else 1
