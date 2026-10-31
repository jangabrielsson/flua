# Batch B response — `--strict-tests` and `--result-json`

Follow-up to `reponse_pt.md`, for the "Using Flua" feedback authors.
Released in **0.1.112** — the batch we scheduled as "Batch B" after your
0.1.111 confirmation (all 32 tests passing, timer and child-removal fixes
verified in the field).

This closes the two remaining P0/P1 items from your proposal list.

## Change 01 — sticky callback failures (`--strict-tests`) ✅

Your exact acceptance test was:

> a timer assertion fails; a later callback prints success and exits 0;
> the final status is still failure. Repeat for UI and transport
> callbacks. A caught expected error passes. Legacy mode keeps its
> documented existing behaviour.

All five are implemented and pinned:

```bash
flua --api local --strict-tests qa.lua     # exit 1 if any callback failed
flua --api local -D strict-tests:true qa.lua   # the declarative spelling
```

- **Sticky**: unhandled errors at the timer, UI and net/mqtt dispatch
  boundaries are recorded and never cleared. A later `_FLUA.exit(0)` does
  not clear the record — the final exit is 1.
- **Boundaries**: timer/UI/action callbacks record at the coroutine
  dispatch; net/mqtt callbacks record at their handler sinks (where those
  errors are actually caught). The record carries the dispatch kind
  (`timer` / `ui` / `net`).
- **Caught errors pass**: an error the QA code catches itself (e.g.
  `pcall`) is not an unhandled callback error and does not fail the run.
- **Opt-in**: without the flag, behavior is unchanged (callback errors
  log and the run continues, like the HC3).

The case you said you would test — a later callback calling
`_FLUA.exit(0)` after an earlier failure — is pinned by
`test_strict_tests_sticky_callback_failure` (the test asserts the later
callback *did* run, prints `LATER OK`, and the process still exits 1).

Minimal repro:

```lua
--%%mode:offline
function QuickApp:onInit()
  setTimeout(function() error("EXPECTED_CALLBACK_FAILURE") end, 10)
  setTimeout(function() print("LATER OK"); _FLUA.exit(0) end, 50)
end
```

```bash
flua --api local --strict-tests repro.lua; echo $?   # 1
flua --api local repro.lua; echo $?                  # 0 (legacy unchanged)
```

## Change 05 — `--result-json` ✅

```bash
flua --api local --strict-tests --result-json result.json qa.lua
```

One machine-readable final record, written atomically (a missing file
after a forceful kill is incomplete — never read it as a pass):

```json
{
  "schemaVersion": 1,
  "status": "failed",
  "exitCode": 1,
  "runtime": {"flua": "0.1.112", "lua": "Lua 5.4", "python": "3.14.3"},
  "clockMode": "realtime",
  "wallSeconds": 0.101,
  "virtualSeconds": 0.063,
  "failures": [
    {
      "kind": "callback_error",
      "callbackKind": "timer",
      "qa": 5000,
      "error": "repro.lua:2: EXPECTED_CALLBACK_FAILURE"
    }
  ],
  "cleanupComplete": true
}
```

- `status` distinguishes **passed** / **failed** / **timeout** — the third
  is the wall-cap case: a `--run-for N` deadline cutting pending work
  short reports `"timeout"` with exit 1, so a hung suite can never look
  green.
- `clockMode` reports how the run was clocked (`realtime`, `speed:N`,
  `instant`, `step`) — the per-run clock field we said in the previous
  response belongs to a result record rather than `--version`.
- The `failures` array is the same record `--strict-tests` uses for its
  exit-code override — one source of truth for both the exit code and the
  JSON.

## What remains (Batch C, unscheduled)

- Change 04 — network policy profiles (`--network-policy
  deny|loopback|allowlist`)
- Change 06 — `--capabilities-json`
- Change 07 — export `--manifest-only`
- Change 09 — event trace + resource summary

None of these blocks the strict-testing workflow; Batch B was the piece
that made CI results trustworthy, which is what your report asked for
first.

Please re-run your suite on 0.1.112 — in particular the
`--strict-tests` + `--result-json` combination on your 30-check harness.
Any findings get the same treatment as before.

— flua maintainers

---

## Follow-up: Batch B verification results and one fix

The authors ran their 32-check suite plus nine strict/result acceptance
cases on 0.1.112 (Windows, Python 3.12.10): **seven passed, two failed** —
both failures were the same gap: an error thrown by a **mapped button
callback** (invoked through `UIAction` or `_FLUA.uiEvent`) was logged but
not recorded, so strict mode exited 0 with an empty failures list.

Their diagnosis was exact: `onUIEvent` schedules the mapped callback via
`callAction`, whose own `xpcall` catches the action error before the outer
coroutine dispatch can see it. Fixed: `callAction`'s framework catch
boundary now records the failure (`kind: "ui"`) while keeping the legacy
log-and-continue behavior and application-owned `pcall` untouched. Their
minimal repro now exits 1 with `status: "failed"` and one `ui` failure
record; both the `_FLUA.uiEvent` and direct `self:UIAction` spellings are
pinned by `tests/test_dx.py::test_strict_tests_covers_mapped_ui_callbacks`.

Their two remaining coverage suggestions (child UI dispatch, ordinary
device actions) are on the list but not yet pinned — flagged honestly
rather than claimed.
