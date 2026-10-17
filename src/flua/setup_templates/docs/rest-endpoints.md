# flua REST endpoints — real vs stub

Which simulated endpoints carry real data and which are HC3-shaped stubs.
The classification rule (from `docs/notes/notes-rest-parity.md`): implement a
stub for real only when (a) a QA calls it, (b) a tool/agent reads it, or
(c) the compat suite flags shape drift. Hand-maintained — update when
`routes/__init__.py` changes.

| Area | Real (state-backed) | Stub (shape-only: empty/zeroed) |
|---|---|---|
| Devices | CRUD (`GET/PUT/DELETE /devices/{id}`), actions, groupAction, `/flua/devices` | — |
| Plugins | variables, child devices, views, restart, UI events, `/flua/embeddedUI` | — |
| House | scenes, rooms, sections, globals, alarm partitions, profiles, customEvents | `/iosDevices`, `/weather` (zeroed values), `/alarms/v1/devices`, `/notificationCenter`, `/energy/devices` |
| Panels | — | `/panels/location`, `/panels/climate`, `/panels/{id}`, `/panels/notifications`, `/panels/family`, `/panels/sprinklers`, `/panels/humidity`, `/panels/favoriteColors` |
| Logs & feeds | `/refreshStates`, `/debugMessages` (+ `tags`, DELETE), `/flua/systemLog` (+ DELETE) | — |
| System | `/settings/info`, `/settings/location`, `/quickApp/*` (files/export), `/proxy`, `/diagnostics` | `/icons`, `/users` |

Notes:

- **Stubs still answer 200 in the HC3's response shape** — they are
  shape-compatible by design (the live compat suite pins that), they just
  carry no data.
- **`/flua/*` routes have no HC3 counterpart** — they are the flua-only
  machine surface (`/flua/devices`, `/flua/embeddedUI`, `/flua/systemLog`).
- The full HC3 surface is much larger than this table (359 endpoints in
  `docs/specs/hc3-api.json`); the sim implements the slice QAs, tools, and
  the viewer actually touch — the rest forwards to the HC3 online.
