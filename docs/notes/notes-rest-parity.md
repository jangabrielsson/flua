# Note: HC3 REST parity for flua

Status: design + implementations (2026-10-16/17).
Implemented: real `/debugMessages` (console buffer) + DELETE + `/tags`;
`/flua/systemLog` (structured system/crash log) + DELETE.

## Context

The HC3's REST API manages QAs (upload/restart/delete), the house resources
(devices, scenes, globals, alarms, …), the event log (`/refreshStates`), and
the QA console (`/debugMessages`). flua's sim implements 77 of those routes
in HC3 shapes (the live compat suite pins them), but several were
shape-only stubs — most notably `/debugMessages`, which returned an empty
buffer while the real QA logs went to stdout/stderr only.

The gap that matters: **agents and tools want the logs over REST**, the same
surface the real HC3 offers — one interface for both, no console parsing.

## Decision: parity is selective

Rule for adding/upgrading a route: implement it for real when (a) a QA
calls it, (b) a tool/agent reads it, or (c) the compat suite shows shape
drift that hurts. Everything else stays a shape-pinned stub. Full parity is
a treadmill (359 endpoints in the spec, shapes drift per firmware).

## Implemented: real `/debugMessages`

HC3 semantics (`fibaro_api_docs/debugMessages.json`, schema `DebugMessageDto`):

- `GET /debugMessages` → `{nextLast, messages: [{id, timestamp, type, tag,
  message}]}`, newest last, bounded ring (10 000 lines, oldest fall off).
- Query params: `last` (only id > last — the poll pattern), `offset`
  (newest N; -1 = all), `filter` (comma list of tags), `types` (comma list),
  `from`/`to` (timestamp bounds, inclusive). Bad numerics → 400.
- `DELETE /debugMessages` → 204, clears the buffer; ids keep growing so
  polling never replays cleared lines.
- `GET /debugMessages/tags` → distinct tags seen so far.

Where the lines come from:

- QA console lines — one tap in `lua/init.lua::formatLogLine` posts the
  structured fields (`_PY.debug_message(level, tag, qaid, msg)`) in both
  log modes; QA `print` maps to `fibaro.debug(__TAG, ...)` → type `debug`.
- flua's own notices — `engine.flua_log` records them (tag `flua` or
  `<name><id>`).
- Untagged runtime lines (JSON mode) — `_handle_log_structured` records
  when `tag is None`. Text-mode untagged lines (`-e` prints, the greeting)
  are not buffered — see open questions.

State: `SimState.debug_messages` (deque, append is thread-safe — the pump
and worker threads both log). Pins: `tests/test_api.py::test_debug_messages`,
`tests/test_qa.py::test_debug_messages_record_qa_logs`.

## Implemented: `/flua/systemLog` (structured system/crash log)

The thing the real HC3 lacks: machine-readable engine lifecycle. flua-only
route (the `/flua/*` namespace), same polling contract as `/debugMessages`
(`last`/`offset`, DELETE):

```json
{"id": 1, "time": "2026-10-17T08:09:26+02:00", "event": "qa_load",
 "qa": 5000, "tag": "name5000", "code": 0, "detail": ""}
```

Events: `run_start`/`run_stop` (engine start/stop), `qa_load`, `qa_restart`,
`qa_exit` (with code), `qa_error` (boot failures, from Lua), `crash`
(callback errors, from Lua), `error` (pump handler / dispatch failures).
Emit points: engine lifecycle methods + `resumeQa`/`startQaInEnv` on the Lua
side (`_PY.system_event`). Pins: `tests/test_api.py::test_flua_system_log`,
`tests/test_qa.py::test_system_log_records_lifecycle_and_crashes`,
`test_system_log_records_boot_failures`.

## Real vs stub — visibility

Planned, not done: a table generated from `routes/ROUTES` marking each
route real vs stub (shape-only), so contributors and agents know which
endpoints carry data. Stubs stay: weather (zeroed), alarms v1 devices,
notificationCenter, energy devices, …

## Open questions

1. Should text-mode untagged runtime lines (the greeting, `-e` prints) land
   in `/debugMessages` too? Requires tagging them at the Python source
   (`engine.post(messages.log(...))` call sites) — cheap but touches the
   greeting/UI-viewer paths.
2. System-log transport: the `/flua/*` REST route is done; a `--log
   system`-style file copy is still open (would mirror `--logfile` for
   agents that prefer files).
3. Buffer bounds (10 000 / 2 000) — enough for agent probing sessions, or
   should they be configurable?
4. Should `offset`'s HC3 quirk ("number of returned messages") be
   documented in USAGE.md alongside the endpoint, or is the pin enough?
