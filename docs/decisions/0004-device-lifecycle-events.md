# 0004 — device lifecycle emits DeviceCreated/DeviceRemoved events

- **Status:** active
- **Date:** 2026-10-15

## Context

Reactive QAs (`RefreshStateSubscriber`, `fibaro.EventMgr`,
`sourceTrigger`) need to learn when devices appear and disappear, exactly
like on the HC3 — where uploading a QA or creating a child emits
`DeviceCreatedEvent` and removal emits `DeviceRemovedEvent`.

## Decision

The sim emits both events in the real HC3's shapes (samples in
`docs/specs/refreshEvents.json`):

- `DeviceCreatedEvent` — `data: {id}`, on QA registration, child creation.
- `DeviceRemovedEvent` — `data: {id, deviceName, type, roomId, roomName,
  sectionName}` (room/section resolved best-effort), on
  `DELETE /devices/{id}` and `removeChildDevice`.

Both carry the standard device-event envelope, land in the refreshStates
feed, and are handed to the pump for subscriber delivery. Proxy devices are
excluded (0003 — the HC3's own event arrives via the poll). Seed loading
and persisted-child restore emit nothing (boot state, like an HC3 reboot).

## Consequences

- Pins: `tests/test_api.py::test_device_created_and_removed_events`,
  `tests/test_qa.py::test_device_created_and_removed_events_reach_subscribers`.
- The event shapes are a compatibility surface — change them only with the
  pins updated deliberately (invariants.md).
