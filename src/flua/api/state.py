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
import time
from collections import deque
from datetime import datetime
from typing import Any

from ..devices import catalog_types, skeleton_for
from ..suncalc import sunrise_sunset

FIRST_RUNTIME_ID = 900000

# How many /debugMessages entries the sim keeps (the HC3's buffer is bounded
# too; the oldest lines fall off).
_DEBUG_MESSAGES_MAX = 10000
# How many /flua/systemLog entries the sim keeps.
_SYSTEM_EVENTS_MAX = 2000

DEFAULT_DEVICE_TYPE = "com.fibaro.binarySwitch"

# the sim's default controller location (Stockholm) until seeded/configured;
# the full HC3 settings/location shape (the plua reference)
DEFAULT_LOCATION = {
    "houseNumber": 0,
    "timezone": "Europe/Stockholm",
    "timezoneOffset": 7200,
    "ntp": True,
    "ntpServer": "pool.ntp.org",
    "latitude": 59.3293,
    "longitude": 18.0686,
    "city": "Stockholm, Sweden",
    "temperatureUnit": "C",
    "windUnit": "km/h",
    "timeFormat": 24,
    "dateFormat": "dd.mm.yy",
    "decimalMark": ".",
}


def _type_error(device_type: str) -> ValueError:
    """Unknown --%%type: suggest close matches (typos) and point at the
    catalog command — the error is read by agents, so it must be actionable."""
    from difflib import get_close_matches

    close = get_close_matches(device_type, catalog_types(), n=3, cutoff=0.6)
    hint = f" — did you mean {', '.join(repr(t) for t in close)}?" if close else ""
    hint += " (all supported types: flua --tool catalog)"
    return ValueError(f"unknown device type: {device_type!r}{hint}")


def _device_skeleton(device_id: int, name: str, device_type: str | None) -> dict[str, Any]:
    # No --%%type defaults to com.fibaro.binarySwitch. A type the catalog
    # does not know falls back to its nearest hierarchy ancestor's skeleton
    # (devices/skeleton_for); only types the hierarchy never heard of are an
    # error (the HC3 would not have them either).
    resolved = device_type or DEFAULT_DEVICE_TYPE
    base = skeleton_for(resolved)
    if base is None:
        raise _type_error(resolved)
    base["id"] = device_id
    base["name"] = name
    base["type"] = resolved  # the device keeps the requested type
    return base


def public(value: Any) -> Any:
    """Deep copy for API responses so callers can't mutate state directly."""
    return copy.deepcopy(value)


class SimState:
    """The simulated HC3: devices, rooms, scenes, globals, profiles, alarms."""

    def __init__(self, seed: dict[str, Any] | None = None) -> None:
        self.devices: dict[int, dict[str, Any]] = {}
        self.plugin_variables: dict[int, dict[str, dict[str, Any]]] = {}  # qa_id -> {name: var}
        self.rooms: dict[int, dict[str, Any]] = {}
        self.sections: dict[int, dict[str, Any]] = {}
        self.scenes: dict[int, dict[str, Any]] = {}
        self.climate_zones: dict[int, dict[str, Any]] = {}
        self.family_locations: list[dict[str, Any]] = []
        self.global_variables: dict[str, dict[str, Any]] = {}
        self.profiles: dict[int, dict[str, Any]] = {}
        self.alarms: dict[int, dict[str, Any]] = {}
        # the controller's location (GET/PUT /settings/location): the HC3
        # computes sunrise/sunset for device 1 from it
        self.location: dict[str, Any] = dict(DEFAULT_LOCATION)
        # runtime overrides from PUT /settings/info and PUT /home — the way
        # a test QA configures the simulated controller at run time. The
        # virtual-clock fields (sun times, date, timestamp) stay computed.
        self.info_overrides: dict[str, Any] = {}
        self.home_overrides: dict[str, Any] = {}
        # PUT /weather (flua extension): fake weather overrides
        self.weather_overrides: dict[str, Any] = {}
        # refreshStates feed: (seq, entry) pairs with strictly increasing seq.
        self.changes: list[tuple[int, dict[str, Any]]] = []
        self.events: list[tuple[int, dict[str, Any]]] = []
        self._refresh_seq = 0
        # debugMessages: the QA console buffer (GET /debugMessages), like the
        # HC3's — {id, timestamp, type, tag, message}, newest last, bounded.
        # Appended from the pump and worker threads (deque.append is atomic).
        self.debug_messages: deque[dict[str, Any]] = deque(maxlen=_DEBUG_MESSAGES_MAX)
        self._debug_seq = 0
        # per-device last-change time (epoch seconds) for the /devices/{id}/
        # properties/{name} envelope — set on every property change, lazily
        # initialized to first-read time before the first change
        self.device_modified: dict[int, int] = {}
        # systemLog (flua-only, GET /flua/systemLog): structured engine
        # lifecycle + crash events — the machine-readable log the real HC3
        # lacks. {id, time, event, qa, tag, code, detail}, newest last.
        self.system_events: deque[dict[str, Any]] = deque(maxlen=_SYSTEM_EVENTS_MAX)
        self._sys_seq = 0
        self.custom_events: list[dict[str, Any]] = []  # POST /customEvents history
        self._next_id = FIRST_RUNTIME_ID
        # Proxy mode (--%%proxy:true): ids of devices the real HC3 owns and
        # this sim only shadows. Updates on them are forwarded to the HC3
        # and never emit local refresh events (the HC3 emits them).
        self.proxy_ids: set[int] = set()
        if seed:
            self.apply_seed(seed)
        # The HC3 always has a partition and a profile; the sim does too
        # unless the seed defines them.
        if not self.alarms:
            self.alarms[1] = {"id": 1, "name": "Home", "armed": False, "breached": False}
        if not self.profiles:
            self.profiles[1] = {"id": 1, "name": "Home", "active": True}
        # Device 1 is the HC3 itself: the zwave primary controller (the
        # HC3's own type for it); its name is the controller name and its
        # properties carry the day's sunrise/sunset (computed on read —
        # see sun_times). A seed may override the entry.
        if 1 not in self.devices:
            self.devices[1] = {
                "id": 1,
                "name": "HC3",
                "type": "com.fibaro.zwavePrimaryController",
                "roomID": 219,
                "properties": {"sunriseHour": "00:00", "sunsetHour": "00:00"},
                "modified": int(time.time()),
            }
        # The HC3 always has the default room, id 219 (new devices land
        # there — see devices.DEFAULT_ROOM_ID) and the default section, also
        # 219, which the default room belongs to. Seeds may override them.
        if 219 not in self.rooms:
            self.rooms[219] = {
                "id": 219,
                "name": "Default room",
                "sectionID": 219,
                "isDefault": True,
                "visible": True,
                "icon": "room_boy",
                "iconExtension": "png",
                "iconColor": "purple",
                "defaultSensors": {"temperature": 0, "humidity": 0, "light": 0},
                "meters": {"energy": 0},
                "defaultThermostat": 0,
                "sortOrder": 1,
                "category": "pantry",
            }
        if 219 not in self.sections:
            self.sections[219] = {"id": 219, "name": "Default section", "sortOrder": 1}
        # The home location panel (GET /panels/location): the panel's
        # lat/long follow the configured location (injected on read, like
        # device 1's sun times). Seeds may override it.
        if not self.family_locations:
            self.family_locations = [
                {
                    "id": 219,
                    "name": "HC3",
                    "radius": 150,
                    "address": "",
                    "home": True,
                }
            ]
        # The controller comes with a default climate zone (panels/climate)
        if not self.climate_zones:
            self.climate_zones[1] = {"id": 1, "name": "Home", "mode": 0, "active": False}

    # -- seeding --------------------------------------------------------------

    def sun_times(self, timestamp: float) -> dict[str, str]:
        """The HC3 device's sunrise/sunset for the virtual clock's current
        date at the configured location (HH:MM, like the HC3 computes)."""
        latitude = float(self.location.get("latitude", DEFAULT_LOCATION["latitude"]))
        longitude = float(self.location.get("longitude", DEFAULT_LOCATION["longitude"]))
        sunrise, sunset, _rise_t, _set_t = sunrise_sunset(latitude, longitude, timestamp)
        return {"sunriseHour": sunrise, "sunsetHour": sunset}

    def snapshot(self, exclude_qa_ids: set[int] | None = None) -> dict[str, Any]:
        """Serializable seed-format document of the persistent sim data.

        Excludes the running QAs (rebuilt from code each run) and the
        transient feeds (refreshStates/events/customEvents). Children are
        excluded here too — they persist under their parent QA's state
        (see the engine's qaState), so the parent id can be remapped per run.
        """
        exclude = exclude_qa_ids or set()
        return {
            "version": 1,
            "rooms": [public(r) for r in self.rooms.values()],
            "sections": [public(s) for s in self.sections.values()],
            "climateZones": [public(z) for z in self.climate_zones.values()],
            "familyLocations": [public(loc) for loc in self.family_locations],
            "scenes": [public(s) for s in self.scenes.values()],
            "globalVariables": {k: public(v) for k, v in self.global_variables.items()},
            "alarms": [public(a) for a in self.alarms.values()],
            "profiles": [public(p) for p in self.profiles.values()],
            "location": public(self.location),
            "devices": [
                public(d)
                for d in self.devices.values()
                if int(d["id"]) not in exclude and not d.get("parentId")
            ],
        }

    def restore_child(self, child: dict[str, Any], parent_id: int) -> None:
        """Re-register a persisted child device under its parent QA (the QA's
        startup children lookup then finds it; new ids stay above it)."""
        child_id = int(child["id"])
        entry = dict(child)
        entry["parentId"] = int(parent_id)
        if "interfaces" not in entry:
            entry["interfaces"] = ["quickAppChild"]
        self.devices[child_id] = entry
        if child_id >= self._next_id:
            self._next_id = child_id + 1

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
                "view": [],
            }
            base.update({k: v for k, v in dev.items() if k not in ("id", "name", "type")})
            if isinstance(base.get("properties"), dict):
                base["properties"] = dict(base["properties"])
            self.devices[dev_id] = base
        for room in seed.get("rooms") or []:
            room = dict(room)
            # rooms without an explicit section land in the default one (219)
            room.setdefault("sectionID", 219)
            self.rooms[int(room["id"])] = room
        for section in seed.get("sections") or []:
            section = dict(section)
            self.sections[int(section["id"])] = section
        for zone in seed.get("climateZones") or []:
            zone = dict(zone)
            self.climate_zones[int(zone["id"])] = zone
        for loc in seed.get("familyLocations") or []:
            if isinstance(loc, dict):
                self.family_locations.append(dict(loc))
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
        location = seed.get("location")
        if isinstance(location, dict):
            for key in ("latitude", "longitude"):
                if key in location:
                    self.location[key] = location[key]

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

    @staticmethod
    def _envelope(
        event_type: str, now: float, source_type: str, device_id: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        """The real HC3's event envelope: type/created/sourceType/objects/data."""
        return {
            "type": event_type,
            "created": int(now),
            "createdMillis": int(now * 1000),
            "sourceType": source_type,
            "sourceId": 0,
            "objects": [{"objectType": "device", "objectId": int(device_id)}],
            "data": data,
        }

    def record_property_event(
        self, device_id: int, name: str, new_value: Any, old_value: Any, now: float
    ) -> None:
        """A device-state change — the interesting feed (events on the real
        HC3, with the full envelope). Emitted only when the value actually
        changes: updateProperty(v) with v already set is silent."""
        if _lua_equal(new_value, old_value):
            return None  # no state change, no event (Lua semantics: true ~= 1)
        self._refresh_seq += 1
        self.device_modified[int(device_id)] = int(now)
        self.events.append(
            (
                self._refresh_seq,
                self._envelope(
                    "DevicePropertyUpdatedEvent",
                    now,
                    "system",
                    device_id,
                    {
                        "id": int(device_id),
                        "property": name,
                        "newValue": new_value,
                        "oldValue": old_value,
                    },
                ),
            )
        )
        return self.events[-1][1]

    def record_action_event(self, device_id: int, action: str, args: list[Any], now: float) -> None:
        """The DeviceActionRanEvent the real HC3 emits for every action."""
        self._refresh_seq += 1
        self.events.append(
            (
                self._refresh_seq,
                self._envelope(
                    "DeviceActionRanEvent",
                    now,
                    "user",
                    device_id,
                    {
                        "id": int(device_id),
                        "actionName": action,
                        "args": list(args),
                        "isSupportedByDevice": True,
                    },
                ),
            )
        )
        return self.events[-1][1]

    def record_device_created(self, device: dict[str, Any], now: float) -> dict[str, Any]:
        """The DeviceCreatedEvent the real HC3 emits when a device appears
        in the system (a plugin device, a QA, or a created child)."""
        self._refresh_seq += 1
        self.events.append(
            (
                self._refresh_seq,
                self._envelope(
                    "DeviceCreatedEvent",
                    now,
                    "system",
                    int(device["id"]),
                    {"id": int(device["id"])},
                ),
            )
        )
        return self.events[-1][1]

    def record_device_removed(self, device: dict[str, Any], now: float) -> dict[str, Any]:
        """The DeviceRemovedEvent the real HC3 emits when a device
        disappears: the device's id/name/type plus its room and section,
        resolved from the sim's rooms/sections (best-effort — a device
        without a room reports an empty one)."""
        room_id = int(device.get("roomID") or 0)
        room = self.rooms.get(room_id)
        section = self.sections.get(int(room.get("sectionID") or 219)) if room is not None else None
        self._refresh_seq += 1
        self.events.append(
            (
                self._refresh_seq,
                self._envelope(
                    "DeviceRemovedEvent",
                    now,
                    "system",
                    int(device["id"]),
                    {
                        "id": int(device["id"]),
                        "deviceName": device.get("name", ""),
                        "type": device.get("type"),
                        "roomId": room_id,
                        "roomName": room.get("name", "") if room is not None else "",
                        "sectionName": section.get("name", "") if section is not None else "",
                    },
                ),
            )
        )
        return self.events[-1][1]

    def mirror_event(self, entry: dict[str, Any]) -> None:
        """An event polled from the real HC3 (online mode): same content,
        local sequence — so api.get('/refreshStates?last=N') serves the
        merged feed."""
        self._refresh_seq += 1
        self.events.append((self._refresh_seq, entry))

    def mirror_change(self, entry: dict[str, Any]) -> None:
        self._refresh_seq += 1
        self.changes.append((self._refresh_seq, entry))

    def record_event(self, name: str) -> None:
        """Record a fired custom event in the refreshStates feed. Firing
        does NOT create the event — creation is POST /customEvents; firing
        (POST /customEvents/{name}) 404s for unknown names."""
        self._refresh_seq += 1
        self.events.append((self._refresh_seq, {"type": "CustomEvent", "data": {"name": name}}))

    # -- debugMessages ------------------------------------------------------------

    def record_debug_message(
        self, type_: str, tag: str | None, message: str, timestamp: float
    ) -> None:
        """Append one console line to the /debugMessages buffer (the HC3's
        DebugMessageDto shape: id, timestamp, type, tag, message). Called
        from the pump and worker threads — pure deque append, never Lua."""
        self._debug_seq += 1
        self.debug_messages.append(
            {
                "id": self._debug_seq,
                "timestamp": int(timestamp),
                "type": type_,
                "tag": tag,
                "message": message,
            }
        )

    def clear_debug_messages(self) -> None:
        """DELETE /debugMessages: empty the console buffer (ids keep growing,
        so polling with last=nextLast never replays cleared lines)."""
        self.debug_messages.clear()

    def record_system_event(
        self,
        event: str,
        qa: int | None,
        tag: str | None,
        detail: str,
        timestamp: float,
        code: int = 0,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one structured lifecycle/crash/trace entry to
        /flua/systemLog. Called from the pump and worker threads — pure
        deque append, never Lua. Event names: run_start, run_stop, qa_load,
        qa_restart, qa_exit, qa_error, crash, error, trace (with ``data``).
        Returns the recorded entry."""
        self._sys_seq += 1
        try:
            when = datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")
        except (OSError, OverflowError, ValueError):
            # exotic --start values: the virtual clock can leave the range
            # datetime handles — fall back to the raw epoch seconds
            when = str(int(timestamp))
        entry = {
            "id": self._sys_seq,
            "time": when,
            "event": event,
            "qa": qa,
            "tag": tag,
            "code": code,
            "detail": detail,
        }
        if data is not None:
            entry["data"] = data
        self.system_events.append(entry)
        return entry

    def clear_system_events(self) -> None:
        """DELETE /flua/systemLog: empty the lifecycle buffer (ids keep
        growing, like debugMessages)."""
        self.system_events.clear()

    # -- global variables --------------------------------------------------------

    def record_global_event(
        self, event_type: str, data: dict[str, Any], now: float
    ) -> dict[str, Any]:
        """A global-variable event (Added/Changed/Removed): the real HC3
        carries a lighter envelope for these — no objects/sourceId, like the
        samples captured from a live controller."""
        self._refresh_seq += 1
        entry = {
            "type": event_type,
            "created": int(now),
            "createdMillis": int(now * 1000),
            "sourceType": "system",
            "data": data,
        }
        self.events.append((self._refresh_seq, entry))
        return entry

    def record_global_added(self, name: str, value: Any, now: float) -> dict[str, Any]:
        return self.record_global_event(
            "GlobalVariableAddedEvent", {"variableName": name, "value": value}, now
        )

    def record_global_changed(
        self, name: str, new_value: Any, old_value: Any, now: float
    ) -> dict[str, Any] | None:
        """GlobalVariableChangedEvent — emitted only when the value actually
        changes (Lua equality, like device property events)."""
        if _lua_equal(new_value, old_value):
            return None
        return self.record_global_event(
            "GlobalVariableChangedEvent",
            {"variableName": name, "oldValue": old_value, "newValue": new_value},
            now,
        )

    def record_global_removed(self, name: str, now: float) -> dict[str, Any]:
        return self.record_global_event(
            "GlobalVariableRemovedEvent", {"variableName": name}, now
        )

    # -- QA registration --------------------------------------------------------

    def register_qa(
        self,
        qa_id: int,
        name: str,
        device_type: str | None,
        properties: Any,
        proxy: bool = False,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Register a running QA as a device (mirrors init.lua's dev table).

        Records the HC3's DeviceCreatedEvent in the feed (returned so the
        engine can hand it to the pump). Proxy-mode QAs are owned by the
        real HC3, which emits the event itself — the poll mirrors it, so no
        local event.
        """
        dev = _device_skeleton(qa_id, name, device_type)
        if isinstance(properties, dict):
            # QA config wins over the type skeleton's default properties.
            merged = dict(dev.get("properties") or {})
            merged.update(properties)
            dev["properties"] = merged
        dev["modified"] = int(time.time())  # fibaro.get's second return value
        self.devices[qa_id] = dev
        if proxy:
            return None
        return self.record_device_created(dev, now if now is not None else time.time())

    def add_base_device(
        self,
        name: str,
        device_type: str,
        properties: Any = None,
        room_id: int | None = None,
        now: float | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Create a base (non-plugin) device from the type skeleton — a
        physical device without a QA behind it, like a db-seeded one, but
        created at runtime (POST /devices). Layer-1 default actions apply.
        Returns (device, DeviceCreatedEvent). Raises ValueError for unknown
        types."""
        device_id = self.new_id()
        dev = _device_skeleton(device_id, name, device_type)
        dev["isPlugin"] = False  # a base device, not a QA
        dev["interfaces"] = [
            i for i in (dev.get("interfaces") or []) if i != "quickApp"
        ]
        if room_id is not None:
            dev["roomID"] = room_id
        if isinstance(properties, dict):
            merged = dict(dev.get("properties") or {})
            merged.update(properties)
            dev["properties"] = merged
        timestamp = now if now is not None else time.time()
        dev["modified"] = int(timestamp)
        self.devices[device_id] = dev
        return dev, self.record_device_created(dev, timestamp)

    # -- proxy mode -------------------------------------------------------------

    def mark_proxy(self, device_id: Any) -> None:
        """Mark a device as owned by the real HC3 (a proxy-mode QA/child)."""
        self.proxy_ids.add(int(device_id))

    def is_proxy(self, device_id: Any) -> bool:
        try:
            return int(device_id) in self.proxy_ids
        except (TypeError, ValueError):
            return False

    def register_proxy_child(self, child: dict[str, Any]) -> dict[str, Any]:
        """Register a child device created on the real HC3 (proxy mode): the
        HC3 assigns the id, the sim shadows it under that same id."""
        child_id = int(child["id"])
        entry = dict(child)
        interfaces = entry.get("interfaces")
        if not isinstance(interfaces, list) or "quickAppChild" not in interfaces:
            entry["interfaces"] = [i for i in (interfaces or []) if i != "quickApp"] + [
                "quickAppChild"
            ]
        self.devices[child_id] = entry
        self.mark_proxy(child_id)
        return entry

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

    @staticmethod
    def is_flua_id(device_id: Any) -> bool:
        """Ids from 5000 up belong to flua (engine-assigned QAs and
        runtime-created devices); lower ids are the HC3's namespace. This is
        how the dispatcher decides whether a 404 is local or must be
        forwarded."""
        try:
            return int(device_id) >= 5000
        except (TypeError, ValueError):
            return False

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


def _lua_equal(a: Any, b: Any) -> bool:
    """Lua's == semantics for event dedupe: numbers equal across int/float,
    booleans only equal booleans, everything else by type and value."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b
