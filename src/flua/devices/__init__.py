"""Device type skeletons from devices.json (the HC3 device catalog).

``devices.json`` is a direct HC3 export: 176 real device captures keyed by
type. It is read and parsed **once per process** (the catalog is ~270KB,
~3ms to parse), then each QA gets a scrubbed deep copy of its type's
skeleton: identity fields (id, name, roomID, ...) are stripped and
instance/secrets scrubbed, so captured data never leaks into the simulated
devices.

If the catalog ever grows large enough that per-type lazy loading matters,
``skeleton_for`` is the single seam to swap for a per-type-file loader.
"""

from __future__ import annotations

import copy
import functools
import json
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).parent / "devices.json"

DEFAULT_ROOM_ID = 219  # the HC3 default room — new devices land here

# Top-level fields that belong to the captured device, not the type.
_IDENTITY_FIELDS = ("id", "name", "roomID", "parentId", "created", "modified", "sortOrder")

# Property keys carrying instance data or secrets from the capture.
_SCRUB_PROPERTIES = (
    "quickAppUuid",
    "ip",
    "userName",
    "username",
    "password",
    "sipUserID",
    "sipUserPassword",
    "log",
    "logTemp",
)


@functools.lru_cache(maxsize=1)
def _catalog() -> dict[str, dict[str, Any]]:
    with open(_CATALOG_PATH, encoding="utf-8") as handle:
        catalog = json.load(handle)
    if not isinstance(catalog, dict):
        raise ValueError(f"invalid device catalog: {_CATALOG_PATH}")
    return catalog


def skeleton_for(device_type: str | None) -> dict[str, Any] | None:
    """Scrubbed deep copy of the type's skeleton, or None for unknown types."""
    if not device_type:
        return None
    source = _catalog().get(device_type)
    if source is None:
        return None
    skeleton = copy.deepcopy(source)
    for field in _IDENTITY_FIELDS:
        skeleton.pop(field, None)
    skeleton["parentId"] = 0
    skeleton["roomID"] = DEFAULT_ROOM_ID
    skeleton["enabled"] = True
    skeleton["visible"] = True
    skeleton["isPlugin"] = True
    skeleton["variables"] = {}
    properties = skeleton.get("properties")
    if isinstance(properties, dict):
        for key in _SCRUB_PROPERTIES:
            properties.pop(key, None)
    interfaces = skeleton.get("interfaces")
    if not isinstance(interfaces, list):
        interfaces = []
    if "quickApp" not in interfaces:
        interfaces = [*interfaces, "quickApp"]
    skeleton["interfaces"] = interfaces
    return skeleton


def catalog_types() -> list[str]:
    """All known device types (sorted, for introspection/tests)."""
    return sorted(_catalog())