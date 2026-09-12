"""Simulated HC3 world state (offline mode).

Single source of truth for everything the REST API serves. Plain dicts,
JSON-serializable, so the same state can be loaded from a ``--seed`` file
and later snapshotted or queried by the online mode. Devices for running
QAs are registered by the engine (ids 5000+); the rest comes from the
seed. Runtime-created entities (child devices) draw ids from a range far
above engine-assigned QA ids, so the namespaces never collide.
"""

from __future__ import annotations

import copy
from typing import Any

from ..devices import DEFAULT_ROOM_ID, skeleton_for

FIRST_RUNTIME_ID = 900000

DEFAULT_DEVICE_TYPE = "com.fibaro.binarySwitch"


def _device_skeleton(device_id: int, name: str, device_type: str | None) -> dict[str, Any]:
    base = skeleton_for(device_type)
    if base is not None:
        base["id"] = device_id
        base["name"] = name
        return base
    # Unknown type (or no type): the minimal skeleton, like the HC3's
    # com.fibaro.binarySwitch default.
    return {
        "id": device_id,
        "name": name,
        "type": device_type or DEFAULT_DEVICE_TYPE,
        "properties": {},
        "enabled": True,
        "visible": True,
        "roomID": DEFAULT_ROOM_ID,
        "parentId": 0,
        "interfaces": ["quickApp"],
        "view": {},
        "variables": {},
    }


def public(value: Any) -> Any:
    """Deep copy for API responses so callers can't mutate state directly."""
    return copy.deepcopy(value)


class SimState:
    """The simulated HC3: devices, rooms, scenes, globals, profiles, alarms."""

    def __init__(self, seed: dict[str, Any] | None = None) -> None:
        self.devices: dict[int, dict[str, Any]] = {}
        self.rooms: dict[int, dict[str, Any]] = {}
        self.scenes: dict[int, dict[str, Any]] = {}
        self.global_variables: dict[str, dict[str, Any]] = {}
        self.profiles: dict[int, dict[str, Any]] = {}
        self.alarms: dict[int, dict[str, Any]] = {}
        # refreshStates feed: (seq, entry) pairs with strictly increasing seq.
        self.changes: list[tuple[int, dict[str, Any]]] = []
        self.events: list[tuple[int, dict[str, Any]]] = []
        self._refresh_seq = 0
        self.custom_events: list[dict[str, Any]] = []  # POST /customEvents history
        self._next_id = FIRST_RUNTIME_ID
        if seed:
            self.apply_seed(seed)
        # The HC3 always has a partition and a profile; the sim does too
        # unless the seed defines them.
        if not self.alarms:
            self.alarms[1] = {"id": 1, "name": "Home", "armed": False, "breached": False}
        if not self.profiles:
            self.profiles[1] = {"id": 1, "name": "Home", "active": True}

    # -- seeding --------------------------------------------------------------

    def apply_seed(self, seed: dict[str, Any]) -> None:
        for device in seed.get("devices") or []:
            dev = dict(device)
            dev_id = int(dev["id"])
            # Seeded devices are the physical "rest of the house", not
            # plugins: build a plain base (no catalog skeleton — the catalog
            # captures are QA plugin instances).
            base = {
                "id": dev_id,
                "name": dev.get("name", ""),
                "type": dev.get("type") or DEFAULT_DEVICE_TYPE,
                "properties": {},
                "enabled": True,
                "visible": True,
                "roomID": 0,
                "parentId": 0,
                "interfaces": [],
                "view": {},
                "variables": {},
            }
            base.update({k: v for k, v in dev.items() if k not in ("id", "name", "type")})
            if isinstance(base.get("properties"), dict):
                base["properties"] = dict(base["properties"])
            self.devices[dev_id] = base
        for room in seed.get("rooms") or []:
            room = dict(room)
            self.rooms[int(room["id"])] = room
        for scene in seed.get("scenes") or []:
            scene = dict(scene)
            scene.setdefault("running", False)
            self.scenes[int(scene["id"])] = scene
        for name, spec in (seed.get("globalVariables") or {}).items():
            value = spec.get("value") if isinstance(spec, dict) else spec
            modified = spec.get("modified", 0) if isinstance(spec, dict) else 0
            self.global_variables[str(name)] = {
                "name": str(name),
                "value": "" if value is None else str(value),
                "modified": int(modified or 0),
            }
        for partition in seed.get("alarms") or []:
            partition = dict(partition)
            partition.setdefault("armed", False)
            partition.setdefault("breached", False)
            self.alarms[int(partition["id"])] = partition
        for profile in seed.get("profiles") or []:
            profile = dict(profile)
            profile.setdefault("active", False)
            self.profiles[int(profile["id"])] = profile

    # -- ids ------------------------------------------------------------------

    def new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    # -- scene / partition lookups ----------------------------------------------

    def scene(self, scene_id: Any) -> dict[str, Any] | None:
        try:
            return self.scenes.get(int(scene_id))
        except (TypeError, ValueError):
            return None

    def partition(self, partition_id: Any) -> dict[str, Any] | None:
        try:
            return self.alarms.get(int(partition_id))
        except (TypeError, ValueError):
            return None

    # -- refreshStates feed -------------------------------------------------------

    def refresh_seq(self) -> int:
        return self._refresh_seq

    def record_change(
        self, device_id: int, name: str, new_value: Any, old_value: Any = None
    ) -> None:
        self._refresh_seq += 1
        self.changes.append(
            (
                self._refresh_seq,
                {"id": int(device_id), "name": name, "newValue": new_value, "oldValue": old_value},
            )
        )

    def record_event(self, name: str) -> None:
        self._refresh_seq += 1
        self.events.append((self._refresh_seq, {"type": "CustomEvent", "data": {"name": name}}))
        self.custom_events.append({"name": name})

    # -- QA registration --------------------------------------------------------

    def register_qa(
        self,
        qa_id: int,
        name: str,
        device_type: str | None,
        properties: Any,
    ) -> None:
        """Register a running QA as a device (mirrors init.lua's dev table)."""
        dev = _device_skeleton(qa_id, name, device_type)
        if isinstance(properties, dict):
            # QA config wins over the type skeleton's default properties.
            merged = dict(dev.get("properties") or {})
            merged.update(properties)
            dev["properties"] = merged
        self.devices[qa_id] = dev

    # -- entities ---------------------------------------------------------------

    def create_child_device(self, parent_id: int, options: dict[str, Any]) -> dict[str, Any]:
        """Create a child device from a /plugins/createChildDevice body."""
        dev = _device_skeleton(self.new_id(), options["name"], options.get("type"))
        dev["parentId"] = int(parent_id)
        initial_properties = options.get("initialProperties")
        if isinstance(initial_properties, dict):
            merged = dict(dev.get("properties") or {})
            merged.update(initial_properties)
            dev["properties"] = merged
        interfaces = options.get("initialInterfaces")
        if isinstance(interfaces, (list, tuple)):
            dev["interfaces"] = list(interfaces)
        else:
            dev["interfaces"] = ["quickAppChild"]
        self.devices[dev["id"]] = dev
        return public(dev)

    def device(self, device_id: Any) -> dict[str, Any] | None:
        try:
            return self.devices.get(int(device_id))
        except (TypeError, ValueError):
            return None

    def plugin(self, plugin_id: Any) -> dict[str, Any] | None:
        """A device that carries a quickApp-style interface (QA or child)."""
        dev = self.device(plugin_id)
        if dev is not None and self.is_plugin_device(dev):
            return dev
        return None

    @staticmethod
    def is_plugin_device(dev: dict[str, Any]) -> bool:
        interfaces = dev.get("interfaces") or []
        return "quickApp" in interfaces or "quickAppChild" in interfaces