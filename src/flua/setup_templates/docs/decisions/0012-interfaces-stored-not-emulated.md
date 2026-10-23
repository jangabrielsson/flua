# 0012 — device interfaces are stored, not emulated

- **Status:** active
- **Date:** 2026-10-23

## Context

HC3 devices (QuickApps included) carry a top-level `interfaces` array.
Recognized interfaces *extend* the device in Fibaro's closed-source engine:
some add properties (e.g. `autoTurnOff` → `autoOffTimestamp`,
`autoOffDefaultTime`), some add actions (→ `setAutoOff`), some alter the web
UI (the auto-turn-off timer on the tile). The semantics are engine-internal
and largely undocumented — the official swagger documents the generic
delayed-action REST mechanism behind auto-turn-off (`delay` on
`POST /devices/{id}/action/{name}`, `DELETE /devices/action/{timestamp}/{id}`)
but not the interface's own action or properties. A real-HC3 device dump
(`src/flua/devices/devices.json`) shows 22 devices carrying `autoTurnOff`
with `setAutoOff` and the two auto-off properties; none of that behavior is
specified anywhere public.

Emulating interfaces would therefore mean guessing at undocumented behavior
per interface, with no way to verify against the real controller except
manual probing.

## Decision

flua keeps the interface **plumbing** but assigns **no semantics** to any
interface:

- Devices store `interfaces` as a plain field, including real data in the
  device catalog (`src/flua/devices/devices.json`).
- The HC3 QuickApp Lua API surface stays: `hasInterface`, `addInterfaces`,
  `deleteInterfaces` (→ `POST /plugins/interfaces`) in
  `src/flua/lua/quickapp.lua`.
- The sim route `plugin_update_interfaces`
  (`src/flua/api/routes/plugins.py`) mirrors the endpoint and the HC3's
  plugin-restart-on-interface-change behavior. It does not validate
  interface names against any list.

Adding an interface stores it and restarts the plugin; it adds **no
properties, no actions, no UI effects**. That is intentional and is not a
bug.

## Consequences

- A QA that calls `self:addInterfaces({"autoTurnOff"})` gets the interface
  stored on its device object and nothing else — it must not be relied on
  to enable any behavior in the sim.
- `tests/test_api.py::test_update_interfaces` pins the storage/removal
  round-trip; `tests/test_sleep.py` pins that an interface add restarts the
  plugin (BOOT counter). Neither asserts semantic side effects — by design.
- The action route (`src/flua/api/routes/devices.py::action_device`)
  ignores the `delay` body field; delayed actions and `autoOffTimestamp`
  bookkeeping stay unimplemented for the same reason.
- If a specific interface is ever emulated, do it per interface: document
  the guessed semantics, add a pinning test, and record it as a new
  decision or an amendment to this one. The plumbing is ready; only the
  semantics are deferred.
