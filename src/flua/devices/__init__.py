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


_SCHEMA_PATH = Path(__file__).parent / "type_schemas.json"

_ZERO_VALUES: dict[str, Any] = {
    "bool": False,
    "int": 0,
    "real": 0.0,
    "string": "",
    "array": [],
    "object": {},
}


@functools.lru_cache(maxsize=1)
def type_schemas() -> dict[str, Any]:
    """The distilled device-type/interface schema (the "compiled" artifact
    scripts/extract_device_schemas.py generates from the local HC3_info
    sources). Types carry their flattened base-type chain: typed
    properties with defaults/enums, the interfaces a device of the type
    gets, and action metadata (argc/args)."""
    with open(_SCHEMA_PATH, encoding="utf-8") as handle:
        schemas = json.load(handle)
    if not isinstance(schemas, dict):
        raise ValueError(f"invalid device type schemas: {_SCHEMA_PATH}")
    return schemas


def _default_value(spec: dict[str, Any]) -> Any:
    """A property's starting value: its declared default, else the type's
    zero value."""
    if "default" in spec:
        return copy.deepcopy(spec["default"])
    return _ZERO_VALUES.get(spec.get("type"), "")


def schema_for(device_type: str | None) -> dict[str, Any] | None:
    """The schema-derived skeleton for a device type: interfaces, typed
    properties at their defaults, and action metadata — or None when the
    schema does not know the type (the capture + hierarchy fallback in
    skeleton_for still applies then)."""
    if not device_type:
        return None
    entry = type_schemas().get("types", {}).get(device_type)
    if entry is None:
        return None
    return {
        "baseType": entry.get("baseType"),
        "interfaces": list(entry.get("interfaces") or []),
        "properties": {
            name: _default_value(spec) for name, spec in (entry.get("properties") or {}).items()
        },
        # the HC3 serves actions as name -> argc (the parity fixture's
        # shape); the full arg metadata stays in type_schemas()/interface_schema()
        "actions": {
            name: int(spec.get("argc", 0)) for name, spec in (entry.get("actions") or {}).items()
        },
    }


def interface_schema(name: str) -> dict[str, Any] | None:
    """One interface's structural facts (typed properties with defaults,
    action metadata), or None when unknown."""
    entry = type_schemas().get("interfaces", {}).get(name)
    if entry is None:
        return None
    return copy.deepcopy(entry)


def property_specs_for(
    device_type: str | None, interfaces: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    """Property name -> spec (type/default/enum) for a device type plus
    any extra interfaces — the lookup the runtime warning and the static
    check both use. Types contribute their flattened base-chain specs;
    interfaces contribute their own."""
    specs: dict[str, dict[str, Any]] = {}
    entry = type_schemas().get("types", {}).get(device_type or "")
    if entry:
        specs.update(entry.get("properties") or {})
    for name in interfaces or []:
        ischema = interface_schema(name)
        if ischema:
            specs.update(ischema.get("properties") or {})
    return specs


def property_type_mismatch(
    device_type: str | None, interfaces: list[str] | None, name: str, value: Any
) -> str | None:
    """A human-readable mismatch when the schema knows `name`'s type/enum
    and `value` does not fit it — the HC3 would silently coerce, flua warns."""
    spec = property_specs_for(device_type, interfaces).get(name)
    if spec is None:
        return None
    ptype = spec.get("type")
    fits = {
        "int": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "real": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "bool": lambda v: isinstance(v, bool),
        "string": lambda v: isinstance(v, str),
        "array": lambda v: isinstance(v, list),
        "object": lambda v: isinstance(v, dict),
    }.get(ptype)
    if fits is not None and not fits(value):
        return f"property {name!r} is declared {ptype}, got {type(value).__name__}"
    enum = spec.get("enum")
    if enum and isinstance(value, str) and value not in enum:
        return f"property {name!r} value {value!r} is not one of its declared enum"
    return None


def apply_interface(device: dict[str, Any], name: str, action: str) -> None:
    """Add/remove an interface with schema semantics.

    On add: the interface's properties join at their defaults (existing
    values stay) and its actions become part of the device's action
    metadata. On remove: the interface's own properties and actions drop —
    except properties the device's TYPE also declares (the type keeps
    those). Unknown interfaces stay the ADR 0012 plumbing: stored, no
    semantics."""
    schema = interface_schema(name)
    if schema is None:
        return
    properties = device.setdefault("properties", {})
    actions = device.setdefault("actions", {})
    type_properties = set((schema_for(device.get("type")) or {}).get("properties") or ())
    if action == "add":
        for prop, spec in (schema.get("properties") or {}).items():
            properties.setdefault(prop, _default_value(spec))
        for action_name, spec in (schema.get("actions") or {}).items():
            actions.setdefault(action_name, int(spec.get("argc", 0)))
    else:
        for prop in (schema.get("properties") or {}):
            if prop not in type_properties:
                properties.pop(prop, None)
        for action_name in (schema.get("actions") or {}):
            actions.pop(action_name, None)


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
