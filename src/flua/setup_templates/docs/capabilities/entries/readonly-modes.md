---
id: readonly-modes
topic: safety
title: --%%mode:readonly[+call] — explore the live HC3 without mutating it
pins:
  - tests/test_api.py::test_readonly_mode_refuses_remote_writes_at_the_gate
  - tests/test_api.py::test_readonly_plus_call_unlocks_device_actions_only
  - tests/test_hc3.py::test_readonly_mode_reads_online_but_never_writes
  - tests/test_hc3.py::test_readonly_plus_call_runs_actions_but_blocks_writes
verified: flua 0.1.169
---

# --%%mode:readonly[+call] — explore the live HC3 without mutating it

The safety posture for agents and test code against a real controller:

- `--%%mode:readonly` — reads behave exactly like online mode; any
  mutating verb (POST/PUT/DELETE) that would reach the HC3 is refused
  with **403** before dispatch. Writes the *sim* owns still work (they
  never touch the controller). No HC3 configured → plain offline.
- `--%%mode:readonly+call` — one unlock: `POST /devices/{id}/action/...`
  (the `fibaro.call` channel) passes through, so test code can flip a
  light on and off to see it work. Creating/deleting resources (and
  every other write) stays blocked. Group actions are *not* unlocked.

The refusal logs a warning (`readonly QA 5000: PUT /devices/45 refused`),
so a silent no-op is always explainable. The gate covers the remote
hook, the helper bridge, and both 404 fallbacks.
