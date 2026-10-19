# 0006 — suspended QAs' remote calls count as pending work

- **Status:** active
- **Date:** 2026-10-15

## Context

After 0005, a second early-exit hole surfaced (CI 3.12, then 3.15 under
8-worker load): a QA's remote `api.*` call suspends the QA and runs on a
`flua-api` worker thread. `has_pending_work()` did not count that worker,
so the CLI's 50 ms idle poll could see "nothing pending" mid-call and end
the run before the response resumed the QA — the QA's output never
appeared.

## Decision

`_api_calls_inflight` counts in-flight remote API calls: incremented in
`_handle_api_call` **before** the worker thread starts (no window where the
counter is behind), decremented in the worker's `finally`, and included in
`has_pending_work()`.

## Consequences

- The graceful-exit contract is: anything a suspended QA can be waiting on
  is pending work. New worker types must follow the same pattern
  (track → count → load-test) — rule 2 in concurrency.md.
- Dropped results after teardown are handled separately
  (`_post_from_worker`), so the counter and the exit path stay orthogonal.
- Pin: `tests/test_hc3.py::test_cli_mode_online_directive_selects_hc3`
  under load; the fix is exercised by every online-mode test.

## Amendment — 2026-10-19: the handoff must be atomic

The original fix still had a hole: the worker enqueued the result via
`loop.call_soon_threadsafe` (deferred until the loop runs the callback) and
decremented `_api_calls_inflight` in its `finally` **immediately**. Between
the two, `has_pending_work()` saw "counter zero, result not yet queued" and
the CLI's 50 ms idle poll ended the run — `dev/hc3_api_filter_test.lua` quit
silently between `api.get` calls in online mode.

`_post_from_worker` now takes a `done` callback and runs enqueue + `done`
together in one loop callback: the counter is decremented only once the
result is visible in `_outbound` (pending or delivered), so the exit poll can
never observe the gap. Pin: `tests/test_engine.py::test_api_result_handoff_is_atomic`.
