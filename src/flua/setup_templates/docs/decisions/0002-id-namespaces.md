# 0002 — three id namespaces

- **Status:** active
- **Date:** 2026-10-15 (retroactive)

## Context

The sim must distinguish "the HC3's own devices" from "devices flua created
for this run" so the hybrid dispatcher knows what to serve locally and what
to forward. QAs, child devices, and the HC3's existing devices all share one
`/devices` space.

## Decision

Three disjoint ranges:

- **< 5000** — the HC3's namespace (seeded house devices, real devices
  online). 404s here forward to the HC3 when a remote backend exists.
- **≥ 5000** — engine-assigned QA ids, starting at 5000, skipping taken
  ids. Always served locally (`SimState.is_flua_id`).
- **≥ 900000** — runtime-created devices (`FIRST_RUNTIME_ID`), i.e.
  children from `createChildDevice`. Never collides with QA ids.

## Consequences

- `Api._dispatch` decides the 404-fallback purely from the id range —
  no per-entity lookup needed.
- A proxy QA breaks the neat range on purpose: it runs under its **HC3**
  id, so the sim shadow and the real device are one id (see the proxy
  invariants in invariants.md).
- Pins: `tests/test_qa.py::test_qa_environments_are_isolated`,
  `tests/test_api.py::test_create_child_device`,
  `tests/test_proxy.py::test_proxy_create_child_device_uses_hc3_id`.
