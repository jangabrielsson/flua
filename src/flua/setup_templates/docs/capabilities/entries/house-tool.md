---
id: house-tool
topic: tooling
title: The house as one JSON — ground truth for agents
pins:
  - tests/test_house.py::test_house_from_hub
verified: flua 0.1.169
---

# The house as one JSON — ground truth for agents

`flua --tool house` dumps the whole house — devices, globals, scenes,
custom events — as a single JSON document (from the configured HC3/hub,
a seed file, or empty offline). It is the agent's ground-truth snapshot:
hand it to a coding agent as context and it knows the real device ids,
types, rooms, and scenes before writing a line of Lua.

- One command, one artifact, `--json`-friendly — pairs with the
  recipes' device pickers and with `--%%db` seeding for offline work.
- Works with or without an HC3: no hub configured → the sim's (empty
  or seeded) world.
- Re-run it after house changes; the snapshot is the context an agent
  should never have to guess.
