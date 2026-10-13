# Note: making flua even easier for agents

Status: tier 1 and 2 implemented (2026-10-13); tier 3 (MCP) deferred.

## Context

A user with a bare `pip install fibaro-flua` + `--tool setup` already has a
working agent loop: self-asserting QA → `flua --api local --instant qa.lua`
→ grep stdout → exit code. The loop leaned on three fragile things:
hand-rolled `expect()` boilerplate, human-formatted log text, and
curl/browser for anything UI-related.

## Shipped (2026-10-13)

- **`require("flua-test")`** — built-in assertions library (expect,
  assert_eq deep compare, assert_json, finish with exit code). Provided by
  the runtime per QA (env-bound: correct log tag and exit attribution in
  multi-QA runs); never travels in the .fqa. Plain Lua, so
  `--%%file:$flua-test.lua,test` ships the same assertions to a real HC3.
  Tests: `tests/test_agent_dx.py`.
- **`--log json`** — JSON-lines QA logs (`{time, level, tag, qaid, msg}`),
  stdout pure JSON, flua notices + the final verdict on stderr. `--logfile
  FILE` appends a copy (ANSI stripped; JSON with `--log json`).
- **UI helpers** — `_FLUA.uiEvent(element, eventType[, value])` injects UI
  events from Lua (HC3 UI delivery semantics, values as strings, async
  callback); `self:getView()` reads the rendered viewLayout incl.
  updateView changes (HC3-compatible API).
- **`--tool ui script.lua`** — the QA's UI as text (elements, callbacks,
  options, values; both viewLayout and uiView formats).
- **Multi-QA exit aggregation** pinned by a regression test, plus a final
  verdict line on stderr (`flua: QA <name> (<id>) exited with code N`).
- Docs: USAGE.md ("Self-testing a QA"), `quickapp-test` and `flua-setup`
  skills.

## Verified facts (probed 2026-10-13)

- **Multi-QA exit aggregation works.** `flua ok.lua failing.lua` exits
  nonzero when any QA fails ("last failing QA wins", `_handle_exit`).
- **UI events can be injected from inside a QA**: `api.get("/plugins/
  callUIEvent?deviceID=" .. self.id .. "&elementName=B1&eventType=onReleased")`
  returns 200 and the QA's callback fires (async — after the call returns).
  `examples/ui.lua` comments already document this pattern.
- **The rendered view is readable from Lua**: `api.get("/plugins/getView?
  id=" .. self.id)` returns the `$jason` viewLayout including `updateView`
  changes.
- UI event values arrive as **strings** (like the real HC3 UI).

## Ideas, ranked

### Tier 1 — the loop itself — DONE

1. Built-in test library via `require` — `require("flua-test")`.
2. Machine-readable output — `--log json` / `--logfile FILE`.
3. UI helpers in Lua — `_FLUA.uiEvent` + `self:getView()`.
4. Text rendering of the UI — `flua --tool ui`.

### Tier 2 — loop robustness — DONE

5. Multi-QA exit aggregation regression test.
6. Per-run log file — `--logfile FILE`.
7. Final verdict line — stderr, every failing QA, any log mode.

### Tier 3 — the long game — DEFERRED

8. **MCP server** exposing run/check/inspect as tools — the agent-ecosystem
   direction (Claude/Copilot hosts). Real project; not a quick win.

   Benefit analysis (2026-10-13): skills = knowledge, `--tool`/CLI = the
   engine's manual interface, MCP = a machine interface for hosts that
   prefer one. Four deltas: (1) typed tool schemas instead of
   arg-string/parse-text friction; (2) hosts with no/unreliable shell
   (Claude Desktop etc.) get flua at all; (3) live stateful sessions — a
   running engine across tool calls (inspect, inject events, poke) vs
   one-shot runs; (4) one standard surface for every host. V1 scope
   suggestion: stdio JSON-RPC, dependency-free, 4-6 tools (check, run with
   instant/json, ui_text, inject_ui_event, devices) wrapping the existing
   engine/tools.

## Known gaps (found while shipping)

- A single `select`'s initial `value` is dropped from the legacy
  viewLayout export (`ui.py` `_layout_element` maps only `values`) — the
  `--tool ui` renderer shows it empty. The uiView format carries it.
  Probably worth fixing in compile_ui, with a test. Full analysis:
  `docs/notes-select-value.md`.
