---
id: recipe-verify-scenarios
topic: tooling
title: Verify scenarios — declarative sim runs that prove a template works
pins:
  - tests/test_builder.py::test_builder_verify_all_runs_every_scenario
verified: flua 0.1.169
---

# Verify scenarios — declarative sim runs that prove a template works

Every recipe manifest can declare a `verify` block — a scenario run in
the sim on a 6000x virtual clock (`flua --tool build --verify <id>`,
`--verify-all`, `--json` for agents; CI gates template changes on it):

```json
"verify": {
  "start": {"time": "12:00"},
  "params": {"deviceId": 1, "offset": 1},
  "steps": [
    {"check": {"device": "deviceId", "value": false}},
    {"waitUntil": {"device": "deviceId", "value": true, "timeout": "12h"}}
  ]
}
```

- Steps: `device` calls (breach, setValue with args), `weather` changes,
  `slider` drags, `wait` (virtual), `waitUntil` (poll until a device
  value, with timeout), and `check` (device value, or QA log lines with
  an exact count).
- `start` anchors the virtual clock: `{time: "12:00"}` (today at noon,
  safely before sunset), a full date-time, or `{before: "sunset",
  by: "2m"}`.
- Device params with nonzero values are seeded from the bundled sim
  devices (a `[sim:<device>]` marker overrides the filter kind).
- Checks retry briefly (reaction chains span pump passes) — the verdict
  measures the outcome, not a race.
