# Changelog

All notable changes to flua. Versions follow the package version; each entry
summarizes the commits in that release (full history:
`git log --pretty=format:"%h %ad %s" --date=short`).

## [0.1.25] - 2026-10-08

### Added
- implement asynchronous API calls for remote backends, allowing non-blocking QA execution
- enhance MQTT TLS support with SNI configuration and add tests

## [0.1.24] - 2026-10-07

### Added
- implement uploadFile tool for single QA file updates and enhance VS Code integration
- add net.*Server extension for mock server functionality

## [0.1.23] - 2026-10-06

### Added
- enhance Lua Language Server support and improve UI handling for multi-selects

### Fixed
- add comments to examples for clarity and remove unused image files

## [0.1.22] - 2026-10-06

### Fixed
- update ignore directories in .luarc.json for improved diagnostics
- add diagnostic directive to suppress type mismatch warning in deviceController.lua
- add ignore directories to .luarc.json for improved diagnostics

## [0.1.21] - 2026-10-06

### Added
- update LuaLS configuration and add type definitions

## [0.1.20] - 2026-10-05

### Fixed
- initialize FOO variable in files2.lua example for dynamic file addition

## [0.1.19] - 2026-10-05

### Changed
- update usage and installation instructions to clarify viewer handling

## [0.1.18] - 2026-10-05

### Added
- add test for runtime file addition persistence in QuickApp

### Changed
- update default modes and improve documentation for HC3 interactions

### Fixed
- enhance breakpoint assertion messages in debugger tests

## [0.1.17] - 2026-10-05

### Changed
- update GitHub Actions to use latest versions of checkout and setup-python

### Fixed
- disable diagnostic for undefined field in hasInterface method

## [0.1.16] - 2026-10-05

### Added
- add endpoint to get plugin view with live state

## [0.1.15] - 2026-10-05

### Added
- add GitHub Actions workflow for testing and scripts for syncing skills
- add PDF build support for tutorial with mermaid diagrams
- add multi-file QA examples and debugging tutorial
- --%%mode:proxy,noUI leaves the proxy UI untouched

### Changed
- Refactor QuickApp templates and add new device types

### Fixed
- initialize QuickAppChild before defining MyBinarySwitch class

## [0.1.14] - 2026-10-05

### Added
- update useUiView to default to false and enhance documentation for flua devices
- update potato_master to use dynamic IDs and modify useUiView default in proxy.py
- remove EOH markers from example scripts and update documentation
- update SunsetLamp to use variables instead of properties for auto mode
- add section on using directives in QuickApp headers for F5 compatibility
- add UI launch configuration and update documentation for VS Code setup

### Changed
- clarify variable usage in QuickApp tutorial

## [0.1.13] - 2026-10-04

### Added
- enhance flua UI viewer and improve QA exit handling
- add Markdown Preview Mermaid extension recommendation for VS Code
- add tutorial chapters for QuickApps and Sunset Lamp example

### Changed
- improve logging messages in potato client and master scripts

## [0.1.12] - 2026-10-04

### Added
- enhance dynamic QA loading with directive support and improve debug configuration
- add UI+mobdebug launch configuration and update documentation

## [0.1.11] - 2026-10-04

### Added
- implement embedded UI support for device types with default views
- automate changelog generation for new releases

## [0.1.10] - 2026-10-04

### Added

- UI viewer restyled after the HC3 look: light theme with white device
  cards, HC3-style buttons, sliders with a blue fill and round knob,
  toggle switches.
- Selects render as collapsed dropdowns (radio circles / check squares in
  the popup), like the HC3 — with the text as a placeholder.
- Components in one `--%%u` row share the row (buttons side by side).
- Label elements render their HTML (`<table>`, `<font color>`, ...).
- Viewer docs in USAGE.md (starting the `--ui` server, the callUIEvent
  contract, proxy mode for the real HC3 UI).

### Changed

- The viewer only rebuilds a device panel when its rendered state actually
  changes (value/structure fingerprint), and never mid-interaction — polls
  are otherwise a no-op, so open dropdowns stay open.

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
