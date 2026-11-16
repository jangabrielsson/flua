---
id: db-seed-persist-replay
topic: sim-world
title: --%%db seeds and persists the house; --%%replay replays a session
pins:
  - tests/test_db.py::test_db_offline_persists_and_restores
verified: flua 0.1.169
---

# --%%db seeds and persists the house; --%%replay replays a session

Two ways to give a sim run a real world:

- `--%%db:house.json` seeds the simulated HC3 from a JSON file
  (devices, rooms, scenes, globals, alarms, profiles) — the same
  schema as `examples/house.json` and the `--seed` flag.
- `--%%db:+house.json` (the `+`) *also persists* emulator state back
  to the file as it changes (atomic writes). What persists follows the
  mode's source of truth: offline the whole sim, online QA state +
  globals, proxy seed-only.
- `--%%replay:house.json` replays a recorded house session
  (`flua record`): seeds the sim and fires the recorded refreshState
  events on the virtual timeline — "it worked yesterday" becomes a
  deterministic reproduction.

`flua --tool createDB -o db.json` captures the real HC3 (device 1,
location, family locations) into a seed file.
