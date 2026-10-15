# 0005 — the pump polls the outbound queue with get_nowait, never wait_for

- **Status:** active
- **Date:** 2026-10-15

## Context

The 0.1.36 CI failures (Python 3.11/3.12; 3.13 green): QAs' work ended
early under load — an online QA's API call never printed, a restarted QA's
third boot never arrived, an instant-mode interval chain died ~17 ticks in.
All were the same defect: the pump consumed messages from `_outbound` with

```python
await asyncio.wait_for(self._outbound.get(), timeout=_PUMP_POLL)
```

On Python ≤ 3.12, when an item landed exactly as the timeout fired,
`wait_for` cancelled the getter and raised `TimeoutError` — **the already
retrieved item was discarded**. A lost timer/restart/API message then made
`has_pending_work()` report idle and the run ended early. Python 3.13
reworked `wait_for`, which is why only 3.13 passed — and why local 3.14
runs never reproduced it.

## Decision

The pump polls without any cancellable get:

```python
try:
    batch = [self._outbound.get_nowait()]
except asyncio.QueueEmpty:
    self._flush_db()
    await asyncio.sleep(_PUMP_POLL)
    continue
```

`get_nowait()` cannot lose an item. Idle cadence (10 ms) and busy-mode
delivery are unchanged.

## Consequences

- Rule for future edits (also in concurrency.md): never cancel a pending
  `Queue.get()`; use polling.
- Verified on 3.11/3.12/3.13/3.14/3.15 under 2- and 8-worker loads.
- 0.1.36 was yanked from PyPI over this; 0.1.37 ships the fix.
