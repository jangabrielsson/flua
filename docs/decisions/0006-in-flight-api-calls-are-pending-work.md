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
