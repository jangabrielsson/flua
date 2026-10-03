# Changelog

All notable changes to flua. Versions follow the package version; each entry
summarizes the commits in that release (full history:
`git log --pretty=format:"%h %ad %s" --date=short`).

## [0.1.9] - 2026-10-03

- `net.HTTPClient`: `options.checkCertificate = false` skips HTTPS certificate
  verification (the HC3 option; default still verifies — tested against a
  self-signed local server).
- `net.WebSocketClient:connect(url, headers)` — headers table as the second
  argument (the HC3 contract).
- New HC3 WebSocket binary mode: `sendBinary(data)` sends binary frames;
  `dataReceived(payload, isBinary)` receives them as raw bytes.
- `flua --tool setup [dir]` — scaffolds a QA project for pip users: `.vscode`
  run/debug configs, `extensions.json`, `.luarc.json`, `AGENTS.md`, and the
  `.github` skills/instructions/prompts (templates ship inside the wheel,
  guarded by a sync test against the repo originals).

## [0.1.8] - 2026-10-02

- Binary-safe TCP/UDP payloads: raw bytes (NUL, >=0x80, literal `\x`
  sequences) round-trip the message bridge byte-for-byte in both directions
  (`_FLUA.escapeBytes` + engine-side un-escape; receive returns raw bytes).
- Flua's own log lines get a distinct format: `[date][FLUA   ][tag]: message`
  (restart messages, `--%%warn` api warnings, unknown-device/handler
  warnings) — QA logs keep their `[DEBUG]/[TRACE]/…` columns.

## [0.1.7] - 2026-10-01

- `--%%location:latitude=N,longitude=N` directive pins the sim's location
  (precedence: default < db file < `.flua.lua` < directive < runtime PUT).
- `.flua.lua` can configure the location (`return { location = {latitude=…,
  longitude=…} }`).
- `flua --tool createDB` — builds an offline db from the real HC3 (device 1,
  `/settings/location`, `/settings/info`, `/panels/location`).
- `/panels/location` serves the seeded familyLocations (persisted in the db).

## [0.1.6] - 2026-10-01

- Device 1 — the HC3 itself: always present, with `sunriseHour`/`sunsetHour`
  computed on read from the virtual clock's date and the configured location
  (suncalc ported from the HC3 algorithm, `src/flua/suncalc.py`).
- `GET/PUT /settings/location` and `GET /settings/info`.
- Default room and section 219 (rooms without a section land in 219), a
  default climate zone, and the batch of GET endpoints `dev/apitest.lua`
  exercises (customEvents, home, debugMessages, weather, alarms devices,
  notificationCenter, profiles/{id}, icons, users, energy, panels/*,
  diagnostics, `/proxy` — plus `POST /customEvents` with a body).
- `fibaro.sleep` works at QA top level and in `onInit`: the QA identity is
  registered (a stub in `qaInstances`) before the file executes; `onInit`
  runs synchronously in `__init`, in the HC3 order (before
  `initChildDevices`).
- `internalStorage` variables persist with the QA's state in `--%%db:+`.

## [0.1.5] - 2026-09-30

- `--%%db:file.json` / `--%%db:+file.json` — seed the sim and (with `+`)
  persist emulator state back: offline the whole house, online the emulator's
  own artifacts (QA state + globalVariables), proxy ignores `+`.
- `fibaro.sleep` queues messages during the sleep and delivers them after
  the callback resumes (arrival order); works in onInit.
- HTML subset in log messages rendered to the terminal (bold/italic/
  underline, font colors, tables, lists, `<br/>`; stripped when colors are
  off).
- `__TAG` bound to `<name><id>` before the QA's files execute (no onInit
  required).
- Issue templates and contributor guidelines.

## [0.1.4] - 2026-09-29

- `--examples` / `flua --examples` prints the installed examples directory
  (the wheel ships the examples).

## [0.1.3] - 2026-09-29

- `--tool` commands: `downloadQA` (unpacks a QA into individual `.lua`
  files, regenerating the `--%%` header and `--%%u` rows), `uploadQA`,
  `updateQA` — one module per tool, auto-discovered.
- Script to extract the HC3 REST API reference from the official swagger
  (→ `docs/specs/hc3-api.json`).
- mobdebug diagnostics/cleanups.

## [0.1.2] - 2026-09-28

- **Proxy mode** — `--%%mode:proxy` mirrors a QA onto the HC3 (reuse/deploy
  a `<name>_Proxy` QA), funnels `onAction`/UI events back, syncs properties
  and UI state, children created on the HC3 mirrored in the emulator.
- `--%%u` UI directives (→ `viewLayout`/`uiView`/`uiCallbacks`) and the
  `--ui` HTTP channel + HTML viewer.
- `--%%keep-alive` directive and the online refreshStates poller.
- Global variable create/update/delete endpoints with refreshState events.
- `os.getenv` environment chain: local `.env` → `~/.env` → process env.
- ARCHITECTURE.md; compatibility and opt-in live-HC3 test suites.

## [0.1.1] - 2026-09-13

- Initial release of the versioned package (release script, PyPI metadata).

## [0.1.0] - 2026-09-13

The first release:

- Lua engine skeleton: lupa (bundled Lua) + asyncio pump, virtual clock,
  message-passing bridge.
- QA timers with attribution/tracking; multiple isolated QAs.
- HC3-compatible `json` module; mobdebug debugger integration.
- WebSocket client (RFC 6455, stdlib-only).
- Device property directives (`--%%properties`/`--%%property`) and
  validation; `flua --check` static checks.
- Versioning, licensing (MIT), release script.
