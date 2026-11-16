---
id: refreshstate-subscriber
topic: events
title: RefreshStateSubscriber — the HC3 event feed, simulated by flua
pins:
  - tests/test_recipes.py::test_motion_lights_reacts_to_the_breach_event
verified: flua 0.1.168
---

# RefreshStateSubscriber — the HC3 event feed, simulated by flua

The mechanism for *reactive* QAs (motion → light instantly, not on a
poll) — the HC3's refreshStates feed, which flua simulates offline:

```lua
local events = RefreshStateSubscriber()
events:subscribe(
  function(event)                          -- predicate: which events
    return event.type == "DevicePropertyUpdatedEvent"
      and event.data and event.data.id == MOTION
      and event.data.property == "value"
  end,
  function(event) self:checkMotion() end)  -- handler
events:run()
```

- The envelope: `{type, data, created}`; a property change carries
  `data = {id, property, oldValue, newValue}`. Edge-trigger on the
  old/new pair for open/close semantics (no cooldown timers needed).
- Events are emitted only when the value actually *changes* (Lua
  equality) — re-setting the same value is silent.
- In flua, a QA with no pending work drains: event-driven QAs keep a
  slow reconcile poll (the recipes use a 5-minute one) that also
  self-heals missed events.
- See `docs/forum/11-refreshstate.html` for the event shapes.
