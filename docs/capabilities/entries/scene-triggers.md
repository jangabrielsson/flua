---
id: scene-triggers
topic: scenes
title: Scenes — COND triggers and sourceTrigger, testable in the sim
pins:
  - tests/test_scene.py::test_date_trigger_evaluates_at_scheduled_fire_time
verified: flua 0.1.166
---

# Scenes — COND triggers and sourceTrigger, testable in the sim

`--%%scene:true` runs a QA as an HC3 Lua scene: a `COND` table of
conditions (device properties, date/cron, custom events, `operator`
any/all) and a body of actions.

- On every matching refreshState event the scene runs its actions with
  `sourceTrigger` and `_sceneId` in scope (a manual execute triggers
  with `{type="manual"}`) — the HC3 semantics.
- Date triggers evaluate `os.date` at the *fire* time, not boot time
  (pinned against the scheduled-evaluation bug).
- flua simulates the trigger feed offline, so a scene is unit-testable
  like any QA: inject events, run on the virtual clock, assert actions.
- The HC3 block editor is the wizard for scene-style automations;
  flua's role is convert → test → understand (ADR 0013).
