---
name: hc3-lua-scenes
description: Write and debug Lua scenes for the Fibaro HC3 / Yubii Home — declarations (triggers and conditions: device, cron, sunrise/sunset, global variables, custom events), actions code, sourceTrigger, scene variables, the restart option, and the scene-vs-QuickApp choice. USE FOR: a "when X then Y" automation, converting a block scene to Lua, a scene that does not start, scene variables, or any mention of fibaro scenes. Also explains what flua can and cannot do with scenes.
---

# HC3 Lua Scenes

## Scene or QuickApp?

| Need | Scene | QuickApp |
|---|---|---|
| React to an event (button, door, time, variable) with a few actions | ✅ | heavier |
| Keep state in memory, run permanently, network I/O (HTTP/TCP/MQTT) | ❌ starts fresh each run | ✅ |
| Buttons / labels in the UI | ❌ | ✅ |

Rule of thumb: QuickApps are the drivers, scenes chain actions by calling QA methods
(`fibaro.call(qaId, "setMode", "Away")`).

## Two parts

1. **Declarations** (conditions / triggers): a Lua *table*, not code — *when* the scene starts.
2. **Actions**: Lua code executed at each start.

Tip: build the scene in **block mode**, then "Convert to Lua" — the HC3 writes exact
declarations (property names, weekday numbers). Conversion is one-way.

## Declarations

```lua
{
  operator = "all",               -- "all" (AND) | "any" (OR); groups can be nested
  conditions = {
    { type = "device", id = 201, property = "value", operator = "==", value = true, isTrigger = true },
    { type = "date", property = "cron", operator = "match", value = {"*", "*", "*", "*", "*", "*"}, isTrigger = false },
  }
}
```

- `isTrigger = true`: a **change** of this condition starts the scene (all conditions are
  then evaluated); `false`: filter only. At least one trigger is needed or the scene never
  starts by itself.
- Operators: `==`, `!=`, `>`, `>=`, `<`, `<=`, `anyValue` (any change), `match` (dates).
- `duration = 60` in a device condition: must stay true 60 s (visible in converted block scenes).
- Condition types: device, central scene button, cron, sunrise/sunset, global variable,
  custom event, alarm, location, weather, HC3 start.

## Actions

```lua
fibaro.debug("MyScene", json.encode(sourceTrigger))      -- first line while developing
if sourceTrigger.type == "device" then                    -- .id, .property, .value
elseif sourceTrigger.type == "date" then
elseif sourceTrigger.type == "user" then                  -- started by hand (Run button, app)
end
```

Functions: `fibaro.call`, `fibaro.getValue`, `fibaro.get` (value + timestamp),
`fibaro.getGlobalVariable` / `setGlobalVariable` (strings), `fibaro.getSceneVariable` /
`setSceneVariable` (persist between runs of the same scene), `fibaro.alert`,
`fibaro.emitCustomEvent`, `fibaro.scene("execute"|"kill", {ids})`, `fibaro.profile`,
`fibaro.alarm`, `fibaro.setTimeout(ms, fn)`, `api.*`, `net.HTTPClient`, `json`.
Logs need a **tag**: `fibaro.debug("Tag", "msg")`.
Notifications: same rules as QuickApps — see the quickapp-api skill, `assets/notifications.md`.

## Traps (read before answering "my scene does not work")

1. No memory between runs → scene variables or global variables.
2. **"Allow restarting a running scene"**: *Yes* = a new trigger kills the running instance
   (pending `setTimeout` lost) and starts again — right for "light off 5 min after the last
   motion"; *No* = triggers are ignored while it runs (including while a `setTimeout` waits).
3. Manual mode ignores declarations.
4. Triggers fire on **changes** only: the same value again does nothing.
5. Value types: switch `true/false`, dimmer / shutter 0–99, sensors numbers; global variables
   are always strings (`== "1"`, not `== 1`); in declarations write `value = true` unquoted.
6. A scene that changes its own trigger device can loop: filter with `sourceTrigger`.
7. Only device **properties** trigger scenes; a QuickApp's internal variable does not (a
   global variable does, and QA property updates like `value` do).
8. Avoid `while true` / long `fibaro.sleep`: use triggers, `setTimeout`, or a QuickApp.
9. Weekday numbering in cron and some property names vary: check a converted block scene.

## flua and scenes

flua does **not execute scene Lua code** — scenes in the offline sim are metadata + run
state, and `fibaro.getSceneVariable` / `setSceneVariable` are stubs (real HC3 only).
What flua does support:

- **Seeding**: the `--seed` JSON file accepts a `"scenes"` array (`{id, name, ...}`).
- **Reading**: `api.get("/scenes")`, `api.get("/scenes/{id}")`.
- **Running/killing**: `fibaro.scene("execute"|"kill", {ids})` → `POST /scenes/{id}/{action}`
  (202) — the sim flips the scene's `running` state.
- **Custom events**: `fibaro.emitCustomEvent(name)` — on the real HC3 these trigger scenes;
  flua delivers them to QAs that define `onCustomEvent(name)` (a flua extension), so the QA
  side of a scene-based design is testable offline.

To develop scene *logic* in flua: port the actions into a QA and drive it with the
quickapp-test skill (simulate the trigger via `--start`, timers, or `api` calls). The
declarations table itself is only testable on a real HC3 (hc3_compat suite).
