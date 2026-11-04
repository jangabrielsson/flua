"""The parity probe list.

Derived from the route registry (``flua.api.routes.ROUTES``) — the single
source of truth for what the sim implements. Every implemented GET becomes
a probe with a concrete path for the offline sim (grounded in the seed
house, ``examples/house.json`` + the QA registered by the replay suite)
and, where the path has placeholders, a resolver that finds a concrete
live id on the HC3 at capture time.

Coverage is pinned by ``tests/hc3_parity/test_hc3_replay.py``: every GET
route is either probed, excluded (flua-only extensions), or unconfigured
(placeholders without a config entry — a bug), so new routes cannot slip
out of the harness silently.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flua.api.routes import ROUTES

# GET routes with these prefixes are flua extensions, not HC3 endpoints —
# there is nothing on the controller to compare against.
EXCLUDED_PREFIXES = ("/flua",)

# A live resolver: client -> concrete path on the HC3, or None when the
# house has nothing to point the probe at (the probe is then skipped).
LiveResolve = Callable[[Any], str | None]

# House-normalizing filter applied to the captured live data before its
# shape is recorded (the replay compares the sim's shape against it).
LiveFilter = Callable[[object], object]


def _first_device_of_type(client: Any, device_type: str) -> str | None:
    devices, status = client.request("GET", "/devices")
    if status // 100 != 2 or not isinstance(devices, list):
        return None
    for device in devices:
        if device.get("type") == device_type:
            return f"/devices/{device['id']}"
    return None


def _first_listed_id(client: Any, path: str) -> str | None:
    """The first id of a list endpoint. /profiles returns a dict wrapper on
    some firmware; everything else returns a plain list."""
    data, status = client.request("GET", path)
    if status // 100 != 2:
        return None
    items = data
    if isinstance(data, dict):
        items = data.get("profiles") if path == "/profiles" else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    return f"{path}/{items[0]['id']}"


def _first_global(client: Any) -> str | None:
    data, status = client.request("GET", "/globalVariables")
    if status // 100 != 2 or not isinstance(data, list) or not data:
        return None
    return f"/globalVariables/{data[0].get('name')}"


@dataclass(frozen=True)
class Probe:
    pattern: str  # the ROUTES path with placeholders — the stable fixture key
    sim_path: str  # concrete path for offline replay (seed house + QA 5000)
    live_path: str | None = None  # static live path (placeholder-free routes)
    live_resolve: LiveResolve | None = None  # resolves the live path at capture
    live_filter: LiveFilter | None = None  # house normalizer on captured data
    note: str = ""  # why the probe is shaped the way it is

    def live(self, client: Any) -> str | None:
        """The concrete path on the HC3, or None when the house cannot
        serve this probe (capture skips it and records the reason)."""
        if self.live_path is not None:
            return self.live_path
        if self.live_resolve is not None:
            return self.live_resolve(client)
        return self.sim_path


def _binary_switch(client: Any) -> str | None:
    return _first_device_of_type(client, "com.fibaro.binarySwitch")


def _first_plugin(client: Any) -> str | None:
    return _first_listed_id(client, "/plugins")


# Per-pattern config for placeholder routes (and house filters for a few
# static ones). Routes without placeholders are auto-probed as-is.
_CONFIG: dict[str, dict[str, Any]] = {
    "/devices": {
        # compare like with like: the sim seed's first device is a
        # binarySwitch, so pin the live shape to binarySwitch devices too
        "filter": lambda devices: [
            d for d in devices if d.get("type") == "com.fibaro.binarySwitch"
        ],
    },
    "/devices/{id}": {"sim": "/devices/10", "resolve": _binary_switch},
    "/devices/{id}/properties/{name}": {
        "sim": "/devices/10/properties/value",
        "resolve": lambda client: (
            path + "/properties/value" if (path := _binary_switch(client)) else None
        ),
    },
    "/rooms/{id}": {"sim": "/rooms/1", "resolve": lambda c: _first_listed_id(c, "/rooms")},
    "/sections/{id}": {
        "sim": "/sections/219",
        "resolve": lambda c: _first_listed_id(c, "/sections"),
    },
    "/scenes/{id}": {"sim": "/scenes/5", "resolve": lambda c: _first_listed_id(c, "/scenes")},
    "/alarms/v1/partitions/{id}": {
        "sim": "/alarms/v1/partitions/1",
        "resolve": lambda c: _first_listed_id(c, "/alarms/v1/partitions"),
    },
    "/profiles/{id}": {"sim": "/profiles/1", "resolve": lambda c: _first_listed_id(c, "/profiles")},
    "/globalVariables/{name}": {
        "sim": "/globalVariables/nightMode",
        "resolve": _first_global,
    },
    "/plugins/{id}": {
        "sim": "/plugins/5000",
        "resolve": _first_plugin,
        "note": "sim: the QA the replay suite registers",
    },
    "/plugins/{id}/variables": {
        "sim": "/plugins/5000/variables",
        "resolve": lambda c: (path + "/variables" if (path := _first_plugin(c)) else None),
    },
    "/plugins/{id}/variables/{key}": {
        # a valid-but-absent key on both sides: pins the 404-on-unknown
        # contract (the HC3's name validation returns 400 for bad names,
        # 404 for well-formed unknowns)
        "sim": "/plugins/5000/variables/fluaParityProbe",
        "resolve": lambda c: (
            path + "/variables/fluaParityProbe" if (path := _first_plugin(c)) else None
        ),
    },
    "/panels/climate/{id}": {
        "sim": "/panels/climate/1",
        "resolve": lambda c: _first_listed_id(c, "/panels/climate"),
    },
    "/customEvents/{name}": {
        # a fixed absent name on both sides: pins the 404 contract without
        # depending on either side having events
        "sim": "/customEvents/fluaParityProbe",
        "note": "absent customEvent on both sides — pins the 404 contract",
    },
    "/customEvents/{name}/publish": {
        # the HC3's second fire endpoint — a GET that publishes (204; 404
        # for unknown names). The absent-name convention keeps the probe
        # side-effect-free on both sides.
        "sim": "/customEvents/fluaParityProbe/publish",
        "note": "absent customEvent — a firing GET, kept side-effect-free",
    },
}


def _build() -> list[Probe]:
    probes: list[Probe] = []
    for method, pattern, _handler in ROUTES:
        if method != "GET" or pattern.startswith(EXCLUDED_PREFIXES):
            continue
        cfg = _CONFIG.get(pattern, {})
        if "{" in pattern and not cfg:
            continue  # unconfigured placeholder route — reported by route_coverage()
        probes.append(
            Probe(
                pattern=pattern,
                sim_path=cfg.get("sim", pattern),
                live_path=cfg.get("path"),
                live_resolve=cfg.get("resolve"),
                live_filter=cfg.get("filter"),
                note=cfg.get("note", ""),
            )
        )
    return probes


PROBES: list[Probe] = _build()
PROBES_BY_PATTERN: dict[str, Probe] = {probe.pattern: probe for probe in PROBES}


def route_coverage() -> dict[str, list[str]]:
    """Every GET route in ROUTES falls into exactly one bucket. The probe
    test pins ``unconfigured == []`` and ``uncovered == []``."""
    probed: list[str] = []
    excluded: list[str] = []
    unconfigured: list[str] = []
    uncovered: list[str] = []
    for method, pattern, _handler in ROUTES:
        if method != "GET":
            continue
        if pattern.startswith(EXCLUDED_PREFIXES):
            excluded.append(pattern)
        elif pattern in PROBES_BY_PATTERN:
            probed.append(pattern)
        elif "{" in pattern:
            unconfigured.append(pattern)
        else:
            uncovered.append(pattern)
    return {
        "probed": probed,
        "excluded": excluded,
        "unconfigured": unconfigured,
        "uncovered": uncovered,
    }
