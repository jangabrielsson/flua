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
import os
import re
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


@functools.lru_cache(maxsize=1)
def _hierarchy() -> dict[str, str]:
    """The offline type hierarchy (child -> parent), distilled from the
    HC3's /api/devices/hierarchy by scripts/extract_hierarchy.py."""
    path = Path(__file__).parent / "hierarchy.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    parents = raw.get("parents")
    return dict(parents) if isinstance(parents, dict) else {}


def skeleton_for(device_type: str | None) -> dict[str, Any] | None:
    """Scrubbed deep copy of the type's skeleton, or None for unknown types.

    A type the catalog does not carry still resolves when the offline
    hierarchy knows it: the nearest cataloged ancestor's skeleton is used,
    so a device type newer than the catalog capture behaves like its base
    instead of erroring."""
    if not device_type:
        return None
    source = _catalog().get(device_type)
    if source is None:
        parents = _hierarchy()
        seen: set[str] = set()
        current = device_type
        while current in parents and current not in seen:
            seen.add(current)
            current = parents[current]
            source = _catalog().get(current)
            if source is not None:
                break
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
    properties = skeleton.get("properties")
    if isinstance(properties, dict):
        for key in _SCRUB_PROPERTIES:
            properties.pop(key, None)
        # the donor device's UI mode is instance state, not type state: a
        # QA/child built from this skeleton defaults to the legacy layout
        # unless it declares --%%useUiView:true itself
        properties["useUiView"] = False
    interfaces = skeleton.get("interfaces")
    if not isinstance(interfaces, list):
        interfaces = []
    if "quickApp" not in interfaces:
        interfaces = [*interfaces, "quickApp"]
    skeleton["interfaces"] = interfaces
    # the catalog captured empty Lua tables as {} where the HC3 declares
    # arrays — normalize the known array fields so the sim serves the same
    # shapes as the real HC3 (and exports parse)
    for key in (
        "categories",
        "initialInterfaces",
        "quickAppVariables",
        "uiCallbacks",
        "uiView",
        "supportedDeviceRoles",
    ):
        value = properties.get(key)
        if isinstance(value, dict):
            value = list(value.values()) if value else []
        elif not isinstance(value, list):
            value = []
        properties[key] = value
    layout = properties.get("viewLayout")
    if isinstance(layout, dict):
        sections = ((layout.get("$jason") or {}).get("body") or {}).get("sections")
        if isinstance(sections, dict):
            items = sections.get("items")
            if isinstance(items, dict):
                sections["items"] = list(items.values()) if items else []
            elif not isinstance(items, list):
                sections["items"] = []
    view = skeleton.get("view")
    if not isinstance(view, list):
        skeleton["view"] = []
    return skeleton


def catalog_types() -> list[str]:
    """All known device types (sorted, for introspection/tests)."""
    return sorted(_catalog())


_ICONS_PATH = Path(__file__).parent / "icons.json"


@functools.lru_cache(maxsize=1)
def _icons_document() -> dict[str, Any] | None:
    """The checked-in icon catalog (scripts/extract_icons.py), or None when
    the file is absent (older installs without the capture)."""
    if not _ICONS_PATH.is_file():
        return None
    with open(_ICONS_PATH, encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"invalid icon catalog: {_ICONS_PATH}")
    return document


def icon_catalog() -> Any:
    """The raw ``GET /api/icons`` payload — the controller's icon library
    (device/room/scene icon sets), stored so the sim serves the HC3's shape
    offline and QA ``deviceIcon`` ids stay aligned with the real controller."""
    document = _icons_document()
    if document is None:
        return None
    return document.get("data")


_ICON_MANIFEST_PATH = Path(__file__).parent / "icon_manifest.json"
_ICON_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_ICON_CONTENT_TYPES = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@functools.lru_cache(maxsize=1)
def icon_manifest() -> dict[str, Any] | None:
    """The checked-in icon file manifest (scripts/extract_icon_files.py):
    ``{meta, files: {set: [names]}, source: {set: dump|hc3}}``, or None when
    the file is absent (older installs)."""
    if not _ICON_MANIFEST_PATH.is_file():
        return None
    with open(_ICON_MANIFEST_PATH, encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"invalid icon manifest: {_ICON_MANIFEST_PATH}")
    return document


def icon_cache_dir() -> Path:
    """The machine-level icon cache — ``~/.flua/icons`` (FLUA_ICON_DIR
    overrides). One cache per user, shared by every project, so the icon
    library is never dumped per repo."""
    override = os.environ.get("FLUA_ICON_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".flua" / "icons"


def icon_file(set_name: str, file_name: str) -> tuple[bytes, str] | None:
    """One cached icon file as ``(bytes, content_type)``, or None when the
    name is invalid or the file is not cached. Names are strictly
    ``[A-Za-z0-9._-]`` and resolved inside the cache — path traversal and
    arbitrary reads are refused by construction."""
    if not _ICON_NAME.fullmatch(set_name) or not _ICON_NAME.fullmatch(file_name):
        return None
    cache = icon_cache_dir().resolve()
    path = (cache / set_name / file_name).resolve()
    if cache not in path.parents or not path.is_file():
        return None
    content_type = _ICON_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return path.read_bytes(), content_type


def icon_default_file(set_name: str, file_extension: str) -> str | None:
    """The icon set's representative state file (the viewer's static
    default): the base file, else the off state, else the multilevel
    middle, else the first file — None when the manifest has no files for
    the set. (Many sets ship no base file — PresenceSensorV1 only has its
    ``0``/``100`` states.)"""
    names = ((icon_manifest() or {}).get("files") or {}).get(set_name) or []
    base = f"{set_name}.{file_extension}"
    if base in names:
        return base
    for suffix in ("0", "50"):
        candidate = f"{set_name}{suffix}.{file_extension}"
        if candidate in names:
            return candidate
    return names[0] if names else None
