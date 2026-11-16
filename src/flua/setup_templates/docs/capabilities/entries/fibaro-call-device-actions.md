---
id: fibaro-call-device-actions
topic: hc3-api
title: Device actions go through fibaro.call, not raw api.post
pins:
  - tests/test_recipes.py::test_recipes_use_fibaro_call_for_device_actions
verified: flua 0.1.168
---

# Device actions go through fibaro.call, not raw api.post

The HC3-idiomatic way to act on a device:

```lua
fibaro.call(lightId, "turnOn")        -- -> POST /devices/<id>/action/turnOn, {args={}}
fibaro.call(tempId, "setValue", 21.5, "C")  -- extra args ride in the args table
```

- Accepts a table of ids to fan out the same action.
- flua's `fibaro.call` asserts the action name is a string and ids are
  numbers — a QA using it here behaves identically on the controller.
- The recipe library bans raw `api.post("/devices/…/action/…")` by test;
  new templates keep the idiom.
- `fibaro.callhc3` forces the direct-HC3 channel (like `api.hc3.*`);
  `fibaro.callGroupAction(name, args)` hits the group-action endpoint
  (note: `--%%mode:readonly+call` unlocks single-device actions only).
