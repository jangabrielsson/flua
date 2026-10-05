# 10 · Debugging multi-QA runs

A real smart home isn't one QuickApp — it's several, talking to each other:
a sensor notices motion, a lamp switches on, a scene dims the room. This
final chapter runs two QAs together and shows how to debug the ensemble.

## The trigger pair

The repo ships a small cast for this chapter: `examples/trigger_sensor.lua`
(the motion sensor) and `examples/trigger_lamp.lua` (the lamp). The sensor
looks the lamp up **by name** and calls its `toggle` action every 600 ms —
the same find-and-call pattern real HC3 QAs use, because ids are assigned at
runtime:

```lua
--%%name:motion-sensor

local function findLamp()
  for _, d in ipairs(api.get("/devices?interface=quickApp")) do
    if d.name == "trigger-lamp" then return d.id end
  end
  return nil
end

function QuickApp:onInit()
  self:debug("sensor online")
  local n = 0
  setInterval(function()
    n = n + 1
    local lamp = findLamp()
    if lamp then fibaro.call(lamp, "toggle") end
    if n >= 3 then os.exit() end
  end, 600)
end
```

```lua
--%%name:trigger-lamp
--%%type:com.fibaro.binarySwitch

function QuickApp:onInit()
  self:debug("lamp online")
end

function QuickApp:toggle()
  local on = not self.properties.value
  self:updateProperty("value", on)
  print("lamp now", on and "ON" or "OFF")
end
```

## Running two QAs at once

flua runs every file you give it — each in its own isolated world, with its
own id, timers and state:

```bash
flua --api local examples/trigger_sensor.lua examples/trigger_lamp.lua
```

```text
🚀 flua 0.1.14 (Lua 5.5, Python 3.14.3), mode offline
[05.10.2026][10:34:26][DEBUG  ][motion-sensor5000]: sensor online
[05.10.2026][10:34:26][DEBUG  ][trigger-lamp5001]: lamp online
[05.10.2026][10:34:27][DEBUG  ][trigger-lamp5001]: lamp now ON
[05.10.2026][10:34:28][DEBUG  ][trigger-lamp5001]: lamp now OFF
[05.10.2026][10:34:28][DEBUG  ][trigger-lamp5001]: lamp now ON
```

Read the **tags**: `motion-sensor5000` speaks first, then `trigger-lamp5001`
answers — the sensor's `fibaro.call` reached the lamp, three times, and the
sensor's `os.exit()` ended the show. With several QAs, the tag is your map:
every log line already tells you *who* said it.

> ✅ **You should see** the sensor announce itself, the lamp answer ON, OFF,
> ON — and the run end by itself.

Run the same pair with the viewer (`flua --api local --ui 8090 …`): both
devices get their own panel, and you can click the lamp's Turn On/Off while
the sensor keeps toggling — two QAs, one UI page.

## The map for ensembles

Three things keep a multi-QA run legible:

- **Tags.** `motion-sensor5000` vs `trigger-lamp5001` — if a line confuses
  you, read its tag first.
- **Levels.** The sensor's "not found yet" is a `self:warning`, the lamp's
  normal chatter is `print` (debug) — reserve `warning`/`error` for things
  that are *wrong*, so they stand out in a busy log.
- **Names over ids.** QAs find each other by name through the API — ids
  change per run (5000, 5001, …), names don't.

## Debugging the whole run

- **Watch mode takes several files**: `flua --api local --watch a.lua b.lua`
  — save either, and only that QA restarts while the other keeps running.
- **mobdebug sees everything.** All QAs share one Lua state, so a
  breakpoint in the lamp's `toggle` stops the whole run — including the
  sensor mid-call — and the debugger shows every QA's variables. Launch a
  multi-file run under the debugger from the terminal:

  ```bash
  flua --api local --debugger=8172 examples/trigger_sensor.lua examples/trigger_lamp.lua
  ```

  (The F5 configurations run the *current file*; for an ensemble, use the
  command line or add the second file to the launch configuration's
  arguments.)

- **Shrink the cast.** When the ensemble misbehaves, chapter 07's rule
  applies doubly: run the suspect QA *alone*, then add the others back one
  at a time. Most "multi-QA bugs" are single-QA bugs with a chatty
  audience.

## Where you are now

That's the whole loop, from `Hello HC3!` to a sensor and a lamp arguing in
your terminal. You can write QuickApps, run and test them offline, debug
them, give them real UIs, grow them into libraries, mirror them onto the
HC3, and — from chapter 06 — deploy them for keeps.

The rest is practice, the flua thread on the Fibaro forum, and the manual
(`USAGE.md`) for the questions this tutorial deliberately skipped. Happy
automating — and mind the sunset.
