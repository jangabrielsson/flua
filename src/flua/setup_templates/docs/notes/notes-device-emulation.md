# Note: device emulation (seeded houses that behave)

Status: layer 1 implemented (2026-10-18) — seeded physical devices react to
the canonical light actions (`turnOn`/`turnOff`/`setValue`) by updating
their `value` property, gated by the catalog's `light` interface. Layer 2
(QAs behind seeded devices) is designed but not built.

## Context

A db/seed file (`--tool createDB`, `--seed`, `--%%db:`) carries the real
house: dozens of devices, fetchable via `/devices`, but inert — `POST
/devices/{id}/action/{action}` only recorded a `DeviceActionRanEvent`.
QAs/plugins have real logic (their actions run the QA's code); physical
devices had none. Layer 1 gives them the canonical default behavior.

## Layer 1 (done)

- `POST /devices/{id}/action/{action}` on a **non-plugin, non-proxy**
  device applies the type's canonical light semantics: `turnOn` →
  `value = true` (dimmers: 99), `turnOff` → false (0), `setValue` accepts
  a number or `"on"`/`"off"`.
- The catalog's `light` interface is the gate — sensors/meters stay inert.
- The change records a `DevicePropertyUpdatedEvent` in the refreshStates
  feed, like a real device would.
- QAs and proxy devices are untouched: their actions keep running real
  code (engine pump / the HC3).

## Layer 2 (design — not built)

Real behavior behind seeded devices, three pieces:

1. **Type-template emulation** — instantiate the `quickapp-types` template
   for a device's type as a QA **pinned to the device's id**, so the
   template's canonical actions run in a real QA environment (timers,
   debug, properties all work). Covers non-QA devices with per-type
   behavior beyond on/off.
2. **Real QA files** — for devices that are QAs on the HC3
   (`interface: quickApp`), `--tool downloadQA` fetches the source; the
   downloaded files run as emulated QAs. Needs one small extension: honor
   **`--%%deviceId:N` as an id pin in the emulator** (today it is
   uploadFile metadata only), so the QA takes its original id and becomes
   the seeded device.
3. **Selection** — the db/seed carries the emulation list
   (`"emulate": [ids]`), `--%%deviceId` pins act as the implicit selection
   for downloaded QAs. Default: nothing emulated (layer 1 only) — with
   100+ devices the user opts in per device. No wildcard.

Open design points: id collisions between pins and engine-assigned ids
(5000+); whether pinned QAs shadow the seeded device entry or replace it;
proxy mode interaction (a pinned QA with the same id as a proxied device
must not double-emit).
