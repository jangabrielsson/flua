# 0009 — the sim serves real logs over REST (debugMessages + systemLog)

- **Status:** active
- **Date:** 2026-10-16/17

## Context

The sim's `GET /debugMessages` was a shape-only stub while the QA logs went
to stdout/stderr only; the HC3 has no structured system/crash log at all.
Agents and tools need the logs over REST — the same surface the HC3 offers,
plus the piece it lacks.

## Decision

Two feeds, one polling contract (`last`/`offset`, `DELETE` to clear):

- **`/debugMessages`** — the QA console buffer in the HC3's
  `DebugMessagesDto` shape with the HC3's query semantics (`filter`/`types`/
  `from`/`to`). Every line records exactly once, in both log modes: QA
  lines via the `formatLogLine` tap (tag `<name><id>`), flua notices via
  `flua_log`/`post_log` (tag `flua`), runtime lines untagged.
- **`/flua/systemLog`** — flua-only, the structured lifecycle/crash feed
  the HC3 lacks: `run_start`/`run_stop`, `qa_load`/`qa_restart`/`qa_exit`
  (with code), `qa_error` (boot failures), `crash` (callback errors),
  `error` (pump/dispatch failures), as `{id, time, event, qa, tag, code,
  detail}`.

Both are bounded rings in `SimState` (deque appends are thread-safe across
pump and worker threads).

## Consequences

- The MCP draft's probe tools can read logs over REST instead of engine
  introspection.
- Pins: `tests/test_api.py::test_debug_messages`,
  `test_flua_system_log`, `tests/test_qa.py::test_debug_messages_record_*`,
  `test_system_log_records_*`.
- Selectivity stays the parity rule (notes-rest-parity.md): these two were
  the surfaces agents/tools actually touch.
