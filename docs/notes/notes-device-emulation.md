# Note: device emulation (seeded houses that behave)

Status: layer 1 implemented (2026-10-18) — seeded physical devices react to
the canonical light actions (`turnOn`/`turnOff`/`setValue`) by updating
their `value` property, gated by the catalog's `light` interface. Layer 2
is partially built (2026-11-26): the `--%%deviceId:N` id pin is honored by
the emulator, so a downloaded QA or a `_FLUA.loadSimDevice` template can be
pinned to a house device's id and take it over. Selection is the seed's
`"emulate"` key (built 2026-11-27).

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
   behavior beyond on/off. Instantiate manually via
   `_FLUA.loadSimDevice("binarySwitch", { "deviceId:45" })` or
   automatically via the seed's `"emulate"` key.
2. **Real QA files** — for devices that are QAs on the HC3
   (`interface: quickApp`), `--tool downloadQA` fetches the source; the
   downloaded files run as emulated QAs. Built (2026-11-26): **
   `--%%deviceId:N` is honored as an id pin in the emulator** — the
   downloaded file's header pin (written by downloadQA) makes it take its
   original id and become the seeded device. A pinned QA replaces a seeded
   plain device at the same id (with a warning); device 1 and running-QA
   ids are rejected; proxy mode ignores the pin; online mode warns that
   the pin shadows a same-id HC3 device.
3. **Selection** — built (2026-11-27): the db/seed carries the emulation
   list (`"emulate": [ids]` or `"emulate": "all"`); `--%%deviceId` pins act
   as the implicit selection for downloaded QAs. Default: nothing emulated
   (layer 1 only) — with 100+ devices the user opts in per device (the
   `"all"` form takes every device with a bundled sim device).

Resolved by the pin (2026-11-26): id collisions between pins and
engine-assigned ids (the counter stays ahead of any pin; a pin onto a
running QA's id is an error); pinned QAs replace the seeded device entry
(with a warning); proxy mode ignores the pin (the HC3 assigns the proxy's
id).
