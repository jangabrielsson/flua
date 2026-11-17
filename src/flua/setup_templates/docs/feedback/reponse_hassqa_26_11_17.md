# Reply: HassQA field report (issue #4) — triaged 2026-11-17

Verified against the current tree (0.1.171 + the session's changes).
What landed, what already existed, what is parked.

## Already solved (discovery gaps)

- **Hung-test kill switch** — `--run-for N` is the hard wall deadline
  (exit 1 when it cuts a busy run) and `--strict-tests` makes uncaught
  callback errors fail the run. Both predate the report; the
  capabilities entries now teach them, and `--deadline SEC` was added
  as an alias so the muscle memory works.
- **CLI variable override** — `-D var:url=...` already did it; `--var
  KEY=VALUE` was added as the shorthand (string values are quoted
  automatically, numbers stay numeric).

## Fixed in this round

- `updateProperty` diagnostic no longer prints the "(the real HC3
  silently ignores the update)" suffix twice.
- `flua-test`: `assert_eq` (deep table compare) and `assert_json`
  already exist in the current lib; messages are now stringified
  safely so a table message cannot crash the library
  (`test_flua_test_assertions_survive_table_messages`). The assertions
  reference lives in the `flua-test-library` capabilities entry.
- `json.encodeFormatted(v[, indent])` — pretty JSON for fixture dumps;
  the compact encoder stays the byte-exact default
  (`test_json_encode_formatted_pretty_prints`).
- `flua --tool test [--dir DIR] [--instant] [--deadline SEC] [--json]`
  — discover `test_*.lua`, run each, one summary, nonzero exit
  (`test_test_tool_runs_a_project_suite`).
- WebSocket lifecycle documented in USAGE.md and pinned as the
  `websocket-lifecycle` capabilities entry: `close()` fires
  `disconnected` exactly once; fresh client per reconnect is the
  supported pattern.

## Parked

- **Undefined-global detection in `--check`** (the highest-value item):
  a real static-analysis pass, not a patch — filed in
  `docs/rainy_day_todos.md` with the rationale. The dynamic channels
  (`--%%warn:stubApi`, `bridge-debug`) cover the runtime half meanwhile.

## Still open for you

- Confirm the `test` runner + `--deadline` shape matches the HassQA CI
  loop; the runner exists to replace the shell loop.
