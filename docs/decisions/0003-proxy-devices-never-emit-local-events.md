# 0003 — proxy devices never emit local refresh events

- **Status:** active
- **Date:** 2026-10-15 (retroactive)

## Context

In proxy mode the real HC3 owns the device; the sim only shadows it under
the same id. Every mutating call is forwarded, and the HC3 emits its own
refreshStates event, which the poller mirrors back into the sim feed. If the
sim also emitted a local event, subscribers would see every change twice.

## Decision

The sim emits **no local refresh event for proxy devices** — not for
property updates, not for actions arriving from proxy callbacks, not for
device create/remove. The single source of events is the HC3, arriving
through the poll's mirror.

## Consequences

- One event per change, guaranteed — the invariant the tests assert
  ("exactly ONE event… a local duplicate would make it two").
- Everything downstream (subscribers, the feed, `EventMgr`) stays
  indistinguishable from a plain online run.
- Pins: `tests/test_proxy.py::test_proxy_update_property_forwarded_event_comes_from_hc3`
  and the no-duplicate assertions on child create/remove.
