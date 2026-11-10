#!/usr/bin/env python3
"""Distill the HC3 device-type/interface sources into flua's own schema.

Reads the local-only source tree (HC3_info/ — gitignored, never shipped):
types/*.xml (device structures: base-type chain, interfaces, typed
properties with defaults, actions), interfaces/*.xml (the properties and
actions an interface adds), and www/json-schema/properties/*.json (enums
referenced by jsonSchema attributes). Emits
src/flua/devices/type_schemas.json — the structural facts flua consumes
for type composition, interface add/remove semantics, and property type
checks. Only the distilled artifact is committed; the sources stay local.

Run locally whenever the source tree changes:
    python3 scripts/extract_device_schemas.py
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "HC3_info"
TYPES_DIR = SOURCES / "types"
INTERFACES_DIR = SOURCES / "interfaces"
JSON_SCHEMA_DIR = SOURCES / "www" / "json-schema"
OUTPUT = ROOT / "src" / "flua" / "devices" / "type_schemas.json"


def parse_literal(text: str):
    """A <default> body: a JSON-ish literal (301, true, "Light", [..], {}).
    Falls back to the raw string when it is not valid JSON."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except ValueError:
        return stripped


def parse_property(elem: ET.Element) -> dict:
    prop = {"type": elem.get("type", "string")}
    extra = elem.get("encrypted")
    if extra is not None:
        prop["encrypted"] = extra == "true"
    extra = elem.get("valuesSet")
    if extra is not None:
        prop["valuesSet"] = extra
    extra = elem.get("hiddenFor")
    if extra is not None:
        prop["hiddenFor"] = extra
    for child in elem:
        if child.tag == "default":
            prop["default"] = parse_literal(child.text or "")
    return prop


def parse_action(elem: ET.Element) -> dict:
    action: dict = {"argc": int(elem.get("argc", 0))}
    args = [{"name": a.get("name"), "type": a.get("type", "string")} for a in elem if a.tag == "arg"]
    if args:
        action["args"] = args
    return action


def load_enums() -> dict[str, list]:
    """jsonSchema refs (e.g. properties/deviceRole.json) -> their enum.
    Two shapes: a direct ``$ref: #/definitions/<key>`` with an enum, and
    an array property whose ``items.$ref`` points at another property
    file (supportedDeviceRoles -> deviceRole)."""
    docs: dict[str, dict] = {}
    if JSON_SCHEMA_DIR.is_dir():
        for path in JSON_SCHEMA_DIR.glob("properties/*.json"):
            try:
                docs[path.name] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
    enums: dict[str, list] = {}
    for name, doc in docs.items():
        ref = doc.get("$ref", "")
        if ref.startswith("#/definitions/"):
            enum = (doc.get("definitions") or {}).get(ref[len("#/definitions/") :], {}).get("enum")
            if isinstance(enum, list):
                enums[f"properties/{name}"] = enum
        # array property: the item vocabulary lives in another property file
        items_ref = ((doc.get("items") or {}).get("$ref")) if isinstance(doc.get("items"), dict) else None
        if isinstance(items_ref, str) and "#/definitions/" in items_ref:
            target_name = items_ref.split("#", 1)[0].rstrip("/").split("/")[-1]
            target = docs.get(target_name, {})
            key = items_ref.split("#/definitions/", 1)[1]
            enum = (target.get("definitions") or {}).get(key, {}).get("enum")
            if isinstance(enum, list):
                enums[f"properties/{name}"] = enum
    return enums


def load_device(path: Path, enums: dict[str, list]) -> dict:
    root = ET.parse(path).getroot()
    device = {
        "type": root.get("type", path.stem),
        "baseType": root.get("baseType") or None,
        "interfaces": [],
        "properties": {},
        "actions": {},
    }
    for child in root:
        if child.tag == "interfaces":
            device["interfaces"] = [i.get("name") for i in child if i.tag == "interface"]
        elif child.tag == "properties":
            for prop_elem in child:
                prop = parse_property(prop_elem)
                ref = prop_elem.get("jsonSchema")
                if ref and ref in enums:
                    prop["enum"] = enums[ref]
                device["properties"][prop_elem.get("name")] = prop
        elif child.tag == "actions":
            for action_elem in child:
                device["actions"][action_elem.get("name")] = parse_action(action_elem)
    return device


def load_interface(path: Path) -> dict:
    root = ET.parse(path).getroot()
    iface = {"name": root.get("name", path.stem), "properties": {}, "actions": {}}
    for child in root:
        if child.tag == "properties":
            for prop_elem in child:
                iface["properties"][prop_elem.get("name")] = parse_property(prop_elem)
        elif child.tag == "actions":
            for action_elem in child:
                iface["actions"][action_elem.get("name")] = parse_action(action_elem)
    return iface


def flatten(types: dict[str, dict]) -> None:
    """Merge each type's base-type chain into it: base properties/actions
    first, the type's own entries (including default overrides) win."""

    def merged(name: str, seen: set) -> dict:
        entry = types[name]
        props: dict = {}
        actions: dict = {}
        interfaces: list = []
        if entry["baseType"] and entry["baseType"] in types:
            parent = merged(entry["baseType"], seen | {name})
            props.update(parent["properties"])
            actions.update(parent["actions"])
            interfaces = list(parent["interfaces"])
        props.update(entry["properties"])
        actions.update(entry["actions"])
        for name_ in entry["interfaces"]:
            if name_ not in interfaces:
                interfaces.append(name_)
        return {"properties": props, "actions": actions, "interfaces": interfaces}

    for name in list(types):
        base = types[name]
        flat = merged(name, set())
        base["properties"] = flat["properties"]
        base["actions"] = flat["actions"]
        base["interfaces"] = flat["interfaces"]


def main() -> int:
    if not TYPES_DIR.is_dir() or not INTERFACES_DIR.is_dir():
        print(f"error: sources not found — expected {TYPES_DIR} and {INTERFACES_DIR}", file=sys.stderr)
        return 1
    enums = load_enums()
    types = {}
    for path in sorted(TYPES_DIR.glob("*.xml")):
        device = load_device(path, enums)
        types[device["type"]] = device
    interfaces = {}
    for path in sorted(INTERFACES_DIR.glob("*.xml")):
        iface = load_interface(path)
        interfaces[iface["name"]] = iface
    flatten(types)
    artifact = {
        "format": "type_schemas/1",
        "types": types,
        "interfaces": interfaces,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        f"wrote {OUTPUT.relative_to(ROOT)}: "
        f"{len(types)} types, {len(interfaces)} interfaces, {len(enums)} enums"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
