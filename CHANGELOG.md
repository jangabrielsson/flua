# Changelog

All notable changes to flua. Versions follow the package version; each entry
summarizes the commits in that release (full history:
`git log --pretty=format:"%h %ad %s" --date=short`).

## [0.1.62] - 2026-10-19

### Changed
- test: improve reliability of HTTP server exit test under CI load

## [0.1.61] - 2026-10-19

### Added
- ensure atomic handoff for API result processing to prevent premature exit

## [0.1.60] - 2026-10-19

### Added
- enhance documentation for HC3 QuickApp package format and Lua scenes; add notifications guide

## [0.1.59] - 2026-10-19

### Added
- update net.HTTPClient to support constructor timeout and enhance usage documentation
- add third-party notices and update license files in pyproject.toml

## [0.1.58] - 2026-10-19

### Added
- add startup patterns and fixed-rate loop examples to SKILL.md
- enhance debugger performance and improve skill accuracy; add example for drift

## [0.1.57] - 2026-10-19

### Changed
- Debugger overhaul: the mobdebug line hook installs only while stepping
  or when breakpoints exist — a plain attached run (VS Code F5/^F5 without
  breakpoints) runs at full speed instead of ~100x slower on hot loops.
  Closed IDE connections detach cleanly (no more "Unexpected socket error:
  nil"), and a `-v` run logs flua's argv + MOBDEBUG_PORT for diagnosing
  host launches.
- Skill corrections: hc3-rest-api endpoints verified against the official
  spec (bogus endpoints removed, alarm partition paths fixed, counts
  reconciled), hc3-write-safety rewritten around the documented
  non-restarting updateProperty channel and device-PUT restart semantics,
  flua-troubleshooting updated, obsolete hc3-vfs skill removed.

### Added
- examples/drift.lua — setInterval drift and work-timing demo.

## [0.1.56] - 2026-10-18

### Added
- add POST /devices endpoint to create base devices from type skeleton
- add caching and building for lupa wheel in CI for Python 3.15

## [0.1.55] - 2026-10-18

### Added
- enhance device property management with new PUT endpoint and update documentation
- add CRUD operations for custom events and update API documentation

## [0.1.54] - 2026-10-18

### Changed
- update CI workflows to use ubuntu-24.04 and enhance Python version support

## [0.1.53] - 2026-10-18

### Added
- implement layer 1 device emulation for seeded physical devices with canonical light actions

## [0.1.52] - 2026-10-18

### Added
- enhance simulated controller settings and endpoints, add PUT support for /home, /settings/info, and /weather

## [0.1.51] - 2026-10-18

### Added
- enhance MQTT error handling and add tests for malformed SUBACK scenarios

## [0.1.50] - 2026-10-18

### Added
- add maxHours parameter to cap virtual time and update related documentation and tests

## [0.1.49] - 2026-10-18

### Added
- enhance error handling and logging in MCP server and tools

## [0.1.48] - 2026-10-18

### Added
- add docs_list and docs_read tools for accessing documentation in MCP server

## [0.1.47] - 2026-10-18

### Added
- add device type catalog tool and enhance error handling for unknown types

## [0.1.46] - 2026-10-18

### Added
- implement concurrency cap for one-shot tools and update documentation
- update README with MCP server details and new tools
- add 'devices' tool to run QA files and return final device list

## [0.1.45] - 2026-10-17

### Added
- implement Streamable HTTP transport for flua-mcp in stateless mode

## [0.1.44] - 2026-10-17

### Added
- implement reusable prompts for debugging and QA templates

### Changed
- Add multi-file QuickApps tutorial and debugging guide

## [0.1.43] - 2026-10-17

### Added
- implement session management and new tools for MCP server

## [0.1.42] - 2026-10-17

### Added
- implement dual-era protocol support for MCP server and update documentation

## [0.1.41] - 2026-10-17

### Added
- implement MCP server with JSON-RPC transport and initial tools

## [0.1.40] - 2026-10-17

### Fixed
- ensure EOF handling reports closed state correctly in tests

## [0.1.39] - 2026-10-17

### Added
- enhance logging capabilities with structured JSON output and add support for Python 3.14
- add support for .fqa files as scripts and enhance logging over REST
- add support for running and checking .fqa packages directly from CLI

### Changed
- Implement HC3 REST API parity for debug messages and system logs
- Implement ADRs for id namespaces, proxy device behavior, and device lifecycle events

### Fixed
- enhance project validation and include checks in the --check command

## [0.1.38] - 2026-10-15

### Fixed
- track in-flight API calls to ensure graceful exit during remote operations

## [0.1.37] - 2026-10-15

### Fixed
- improve outbound queue handling and error management in LuaEngine fix: handle OSError in EchoServer to prevent thread noise during timeout tests

## [0.1.36] - 2026-10-15

### Changed
- Housekeeping

## [0.1.35] - 2026-10-14

### Fixed
- ensure proper closure of HTTPError responses to prevent warnings at GC time

## [0.1.34] - 2026-10-14

### Added
- implement DeviceCreatedEvent and DeviceRemovedEvent handling in API and state management

### Changed
- Add serial execution option for pytest, improve sleep durations, and enhance test stability
- add initial draft for distribution surfaces including package managers and VS Code extension
- add benefit analysis for MCP server and tool schemas in notes-agents.md

### Fixed
- update logging messages and improve event handling in documentation and code

## [0.1.33] - 2026-10-13

### Added
- enhance flua-test library with support for assertions on HC3 and add new documentation for agent features

### Fixed
- update lupa dependency to version 2.8 for improved compatibility with Lua 5.5
- comment out unused variable assignment in potato_client.lua

## [0.1.32] - 2026-10-13

### Added
- add structured logging and UI helpers for QAs
- simplify flua installation instructions for Windows 11 and clarify usage without a virtual environment
- add comprehensive installation guide for flua on Windows 11

## [0.1.31] - 2026-10-12

### Added
- add installation guide for Windows 11 including Python, pip, and VS Code setup
- add installation guide for macOS including Python, pip, and VS Code setup
- enhance Windows compatibility and UTF-8 handling in CLI and logging
- add verification instructions for virtual time in QuickApp development
- add initial documentation for MQTT broker concept to aid testing

### Changed
- remove outdated Windows installation guide
- update viewer path references and remove obsolete index.html

## [0.1.30] - 2026-10-11

### Added
- enhance variable handling in packaging tools and documentation

## [0.1.29] - 2026-10-09

### Changed
- Add source trigger event handling in sourcetrigger.lua

## [0.1.28] - 2026-10-09

### Added
- add custom event handler and update test for custom events in event_tests
- add global variable event handler and update test timing for improved execution flow
- update weather event handling methods to setTemperature, setHumidity, and setWind for consistency
- add bundled library support with $ prefix for event handling and improve QA file management
- add support for _FLUA.postRefreshEvent and qa_mode, enhancing event handling and runtime mode reporting

## [0.1.27] - 2026-10-08

### Added
- enhance QA environment isolation by ensuring each QA's _G is its own globals

## [0.1.26] - 2026-10-08

### Added
- implement --%%include directive for default configuration management and enhance directive handling
- update config pipeline documentation to clarify directive handling and include expansion

### Changed
- remove offline mode directive from .directives file

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
