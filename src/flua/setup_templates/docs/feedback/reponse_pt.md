# Response to "Using Flua to test and debug Fibaro QuickApps"

Reply to the experience report (`pt_using_flua.md`) and the change
proposals (`pt_using_flua_proposed_changes.md`), 31 October 2026. Addressed
in release **0.1.111**.

Thank you for this report — it is the kind of feedback we can act on
directly: reproductions instead of impressions, acceptance criteria per
proposal, and a clear statement of what was *not* qualified (debugger,
proxy, physical devices). We verified both P0 reproductions against the
then-current release and confirmed them, then triaged the nine change
proposals into three batches. This document records what shipped, what is
scheduled, and where we made a different call than the proposal.

## Verified reproductions

Both P0s reproduced on 0.1.110 exactly as described:

1. **Unhandled timer error → exit 0.** The callback error and traceback
   print, but the process exits 0 — and a later `_FLUA.exit(0)` cannot
   clear it because no failure state exists. Confirmed.
2. **Instant-mode clock jump.** With `--instant --run-for -3`, the 1 s
   timer observed `os.time() - start == 2` because a 2 s timer was also
   queued. Root cause: instant mode swept the whole timer heap in one pass
   and advanced the clock to each deadline as it *popped* them — so by the
   time the pump delivered the first callback, the clock already read the
   last deadline. Confirmed.

## What shipped in 0.1.111

### Change 02 — instant-mode callbacks observe their own deadlines (P0) ✅

`--instant` now uses the same deadline-ordered discipline as `--step`:
only the earliest timer fires per pump pass, and the clock advances to
*its* deadline just before its callback runs. Both modes share one
`deadline_ordered` clock property, so `--instant` and `--step` are now the
same fast-forward semantics (under two names — `--step` keeps the plua
spelling). `--speed` remains the continuous clock, with its documented
"virtual time passes while your code executes" caveat.

- Your two-timer reproduction passes in both modes; the assertion
  `TIMER_TEST_COMPLETE` now prints and the run exits 0.
- New regression tests: the two-timer fixture end to end (instant + step),
  nested-timer ordering (a timer scheduled from a callback lands between
  the remaining ones), and the TimerManager unit test updated to the new
  single-fire contract.
- One nuance worth knowing when writing such fixtures: `os.time()` returns
  whole seconds (Lua truncates), so sub-second deadlines are not
  assertable through `os.time()` deltas — use integer-second deadlines in
  assertions (our tests do).
- USAGE.md no longer documents instant mode as "unsafe for
  `os.time()`-relative logic" — that caveat was the bug.

### Change 03 — `QuickApp:removeChildDevice(id)` (P1) ✅

Implemented on the real HC3 endpoint,
`DELETE /plugins/removeChildDevice/{id}` (the simulated route already
existed: 404 for unknown ids, 501 for non-children, 204 on success, with
device-removed events). The method is guarded to the QA's own children —
a foreign id returns nothing and the child stays in the inventory — and a
successful removal clears the QA's local `self.childDevices` entry, so a
repeated call returns nothing instead of re-deleting.

- Parity tests: create → remove → REST inventory agrees → repeat returns
  nothing; a second QA cannot remove a foreign child.
- The stale-reference behavior you asked us to document: after removal the
  QA's local reference is cleared, and any *other* captured reference is
  the caller's responsibility — matching the REST contract.

### Change 08 (partial) — runtime diagnostics ✅

`flua --version --machine` now reports:

```json
{"version": "0.1.111", "lua": "Lua 5.4", "lupa": "2.6",
 "python": "3.14.3", "integerBytes": 8, "locale": "C/C.UTF-8/C/C/C"}
```

Lua/Python/Lupa versions, native integer width, and locale — the fields
you asked for. The clock mode is not in there yet (it is not meaningful
for `--version`); it belongs to a per-run result record instead, which
ties into Change 05 below.

### Tooling follow-ups from your report

- **LuaLS annotations**: a new `.luals/net.lua` types the whole `net.*`
  surface (HTTPClient/TCPSocket/UDPSocket/WebSocketClient(Tls) + the four
  server classes), and `.luarc.json` gains the log-level globals
  (`NONE`/`ERROR`/`WARNING`/`DEBUG`/`TRACE`/`LOG_LEVEL`) — the packaged
  copies ship with the wheel, guarded by a byte-equality sync test.
- **Log levels**: `QuickApp:debug/trace/warning/error` now respect the
  `LOG_LEVEL` global (default: everything logs, like the HC3; a QA may
  lower it).

## What is scheduled, per the agreed split

### Batch B (next release) — the remaining P0 and its companion

- **Change 01 — sticky callback failures (`--strict-tests`).** Opt-in, so
  the default keeps mirroring the HC3 (where callback errors log and the
  QA continues). Unhandled errors at the timer/UI/transport dispatch
  boundaries record into run-owned failure state; a later `_FLUA.exit(0)`
  cannot clear it; the final exit is 1. Acceptance tests exactly as you
  specified (timer, then UI and transport; a caught expected error still
  passes).
- **Change 05 — `--result-json`.** A machine-readable final record
  (schema v1: status, exitCode, runtime, clockMode, wall/virtual seconds,
  failures with kinds) written atomically; a missing file after a kill is
  incomplete, never a pass. The failures field feeds directly from Change
  01. The independent wall-time supervision you proposed is the one piece
  we are still designing — see below.

### Batch C (scheduled separately)

- **Change 04 — network policy profiles.** Agreed it is valuable — your
  audit-hook wrapper shows the need — but it is a feature of its own:
  deny-before-connect across HTTP/WebSocket with DNS and redirect rules is
  easy to get subtly wrong, so we want it tested on its own rather than
  bundled. Not a security sandbox for arbitrary Lua/Python — we will say
  so in the docs, as you suggested.
- **Change 06 — `--capabilities-json`** (implemented/partial/unsupported
  table, probed by tests).
- **Change 07 — export `--manifest-only`** (file/secret preview without
  printing resolved values).
- **Change 09 — event trace + resource summary.** Partial infrastructure
  already exists (structured `net`/timer trace events, the timeline); the
  QA-lifecycle resource inventory is new.

## Points where we made a different call

- **Change 01 exit code**: we will use exit code 1 for a strict failure
  rather than inventing a new code — simpler for CI, with the JSON result
  carrying the failure kinds.
- **Change 05 wall supervision**: a timeout implemented inside the Lua
  interpreter cannot fire while Lua is on the stack; your own note
  ("supervision may need an outer process") is correct and matches our
  design. The outer supervisor will be the CLI's wall cap, not a callback
  inside the interpreter.
- **Capability claims**: we agree with the report's framing and will keep
  the matrix "verified by executable probes", never claims about firmware
  parity.

## Please re-run your suite

All of this is in `fibaro-flua==0.1.111`. Your two P0 fixtures should now
behave as specified (the clock one is fixed; the exit-code one is the last
item of Batch B and still reproduces — by design, until `--strict-tests`
ships). The 30-check suite result and any new findings are welcome; the
same triage process applies.

— flua maintainers

---

## Follow-up from the feedback author

Received after 0.1.111:

> Thanks for the fixes and the detailed response. We (me and Codex :) )
> reran the suite on Flua 0.1.111, and all 32 tests passed. We verified
> the timer fixes, including nested timers in both --instant and --step,
> as well as child removal and registry/REST consistency. Once
> --strict-tests is released, we'll also test callback-error exit codes,
> including the case where a later callback calls _FLUA.exit(0).

Status: Batch A confirmed in the field. Batch B (`--strict-tests` +
`--result-json`) is the remaining work, and the author has committed to
testing the sticky-exit-code behavior when it ships.
