# Requirements-flow spec format — draft v0.1 (worked example)

Status: format draft — the artifacts below were built and **run against
current flua** (dusk and noon scenarios, R1–R4 all PASS, exit codes 0).
This is the first concrete proposal for the spec schema from
`notes-requirements-flow.md`; argue over this, not the abstract.

The spec is the only artifact that crosses loop boundaries: loop 1
(user ⇄ agent) produces it, loop 2 (agent ⇄ testbed) consumes it, and a
"not quite" at the demo gate re-enters loop 1 as a spec diff. It
compiles three ways: the **emulator seed** (the house section), the
**check scaffold** (the requirements' checks), and the **driving prompt**
(spec + house + loop protocol — not rendered here; see the note).

## The spec

```markdown
---
spec: 0.1
name: Hall light on motion
template: motion-light
status: approved                # draft → approved (end of loop 1) → done (4b)
house:
  rooms:
    hall:
      motion: {type: com.fibaro.binarySensor, name: "Hall motion"}
      light:  {type: com.fibaro.binarySwitch,  name: "Hall light"}
requirements:
  - id: R1
    text: motion after sunset turns the hall light on
    check: "seed at dusk; flip HT.hall.motion; the light is on within seconds"
  - id: R2
    text: the light turns off after 5 minutes without motion
    check: "after R1, no more motion; the light is off at +5 minutes"
  - id: R3
    text: switching the light off manually during the 5 minutes cancels
          the auto-off, and a new motion starts a fresh cycle
    check: "after R1, switch the light off; new motion; the light is on again"
  - id: R4
    text: motion before sunset does nothing
    check: "seed at noon; flip HT.hall.motion; the light stays off"
constraints:
  - offline sim unless the user asks otherwise
  - symbolic refs only (the homeTable idiom); no baked device ids
  - the agent never deploys
---
```

Invariants the format must keep (the acceptance criteria for v0.1):

- **Symbolic refs, never ids.** House entries are named; the code and
  checks address `HT.hall.motion`, not 10.
- **Requirement ids are the contract.** Every requirement carries an id;
  the check scaffold maps 1:1; a refinement is a visible diff ("R2: 5 →
  10 minutes").
- **Diffable.** YAML/markdown, line-oriented, version-control friendly —
  the loop-1 dialogue history is the spec's diff history.
- **The house section compiles to the seed.** Rooms/devices/types are
  exactly what `--seed` accepts; the sim's device catalog provides the
  types (`newQA`'s 30-type set), so the interview can offer real
  choices.

## What it compiles to

**The seed** (house.json — from the `house` section):

```json
{"devices": [
  {"id": 10, "name": "Hall motion", "type": "com.fibaro.binarySensor",
   "properties": {"value": false}},
  {"id": 11, "name": "Hall light", "type": "com.fibaro.binarySwitch",
   "properties": {"value": false}}
]}
```

(Ids here are the emulator's namespace — the symbolic names stay
authoritative; a real-HC3 ground truth via `--tool house` replaces the
interview-built section.)

**The check scaffold** (hall_light_test.lua — one check per requirement
id, phrased in the requirement's words; the dusk run covers R1–R3, the
noon run R4):

```lua
--%%name:HallLightTest
local Test = require("flua-test")
local t = Test.new()

function QuickApp:onInit()
  local motion, light
  for _, d in ipairs(api.get("/devices")) do
    if d.name == "Hall motion" then motion = d.id end
    if d.name == "Hall light" then light = d.id end
  end
  local function value(dev) return api.get("/devices/" .. dev).properties.value end
  local function flip(dev, v) api.put("/devices/" .. dev, { properties = { value = v } }) end
  local function waitFor(what, untilTrue, deadline, done)
    if untilTrue() then t:expect(true, what) done() return end
    if os.time() > deadline then t:expect(false, what) done() return end
    setTimeout(function() waitFor(what, untilTrue, deadline, done) end, 50)
  end
  local now = os.date("*t")
  local h, m = fibaro.getValue(1, "sunsetHour"):match("(%d+):(%d+)")
  local dusk = tonumber(h) * 60 + tonumber(m)
  local nowMin = now.hour * 60 + now.min

  if nowMin >= dusk then
    flip(motion, true)
    waitFor("R1: motion after sunset turns the hall light on",
      function() return value(light) == true end, os.time() + 3, function()
      flip(light, false)
      flip(motion, false)   -- triggers fire on changes only: reset first
      flip(motion, true)
      waitFor("R3: manual off cancels the timer, new motion starts a fresh cycle",
        function() return value(light) == true end, os.time() + 3, function()
        waitFor("R2: the light turns off after 5 minutes without motion",
          function() return value(light) == false end, os.time() + 320, function()
          t:finish()
        end)
      end)
    end)
  else
    flip(motion, true)
    setTimeout(function()
      t:expect(value(light) == false, "R4: motion before sunset does nothing")
      t:finish()
    end, 3000)
  end
end
```

Run: `flua hall_light.lua hall_light_test.lua --seed house.json --start
"2026/6/20 22:30:00" --speed 300` → `R1 PASS, R3 PASS, R2 PASS,
failures: 0, exit 0`; the noon run (`--start "2026/6/20 12:00:00"`) →
`R4 PASS`. (Both executed against flua 0.1.138 while writing this.)

**The reference implementation** — the template's known-good approach
that the driving prompt hands the agent (not generated code; the agent
adapts it). `hall_light.lua` resolves devices by name at boot (homeTable
minimal form), reacts via RefreshStateSubscriber, and gates on sunset:

```lua
--%%name:HallLight
function QuickApp:onInit()
  self.motion, self.light = nil, nil
  for _, d in ipairs(api.get("/devices")) do
    if d.name == "Hall motion" then self.motion = d.id end
    if d.name == "Hall light" then self.light = d.id end
  end
  self.timer = nil
  local rss = RefreshStateSubscriber()
  rss:subscribe(function(e)
    return e.type == "DevicePropertyUpdatedEvent"
      and (e.data.id == self.motion or e.data.id == self.light)
      and e.data.property == "value"
  end, function(e) self:event(e.data) end)
  rss:run()
end

function QuickApp:event(data)
  if data.id == self.motion and data.newValue == true then
    local h, m = fibaro.getValue(1, "sunsetHour"):match("(%d+):(%d+)")
    local now = os.date("*t")
    local dusk, nowMin = tonumber(h) * 60 + tonumber(m), now.hour * 60 + now.min
    if nowMin >= dusk then self:startCycle() end
  elseif data.id == self.light and data.newValue == false and self.timer then
    clearTimeout(self.timer)
    self.timer = nil
  end
end

function QuickApp:startCycle()
  fibaro.call(self.light, "turnOn")
  if self.timer then clearTimeout(self.timer) end
  self.timer = setTimeout(function()
    self.timer = nil
    fibaro.call(self.light, "turnOff")
  end, 5 * 60 * 1000)
end
```

**The checklist render** (the demo gate's verdict pane):

```
Hall light on motion — requirements
  R1  motion after sunset turns the hall light on          PASS
  R2  the light turns off after 5 minutes without motion   PASS
  R3  manual off cancels the auto-off; new motion cycles   PASS
  R4  motion before sunset does nothing                    PASS
```

## What building it surfaced

- **Triggers fire on changes only** — the scaffold had to reset the
  motion sensor between cycles, or R3 silently tested nothing. A
  scaffold author will keep stepping on this; the *template library*
  should carry it as a standard note.
- **Chained checks need the chain.** R2 alone ("light is off") can
  false-positive when an earlier check broke the state; the scaffold's
  chain structure (R1 success → R3 → R2) makes each check meaningful in
  context. Weak checks = weak requirements — an agent-side analysis rule
  for the checklist ("a check must verify the transition, not just the
  end state"), not a fact flua can lint.
- **R3's wording is a decision, not a fact.** "Manual off wins" could
  mean sticky (ignore motion until manual on) or fresh-cycle (this
  draft's reading). The spec recorded *one* reading; the other is a
  one-line spec diff away. This is exactly the loop-1 dialogue made
  visible — and a candidate for the first real template-library entry.

## Schema questions to argue over

1. **House refs**: room-keyed nesting (`hall.motion`) vs flat names
   (`motion.hall`)? Room-keyed reads like the extension's ht.lua;
   flat survives device moves between rooms better.
2. **`check` depth**: one-line acceptance wording (this draft) vs a
   structured check DSL (flip/wait/assert steps) that compiles to the
   scaffold deterministically? The former is human; the latter is
   compilable — maybe both (wording + optional steps).
3. **Constraints**: is a fixed constraint vocabulary enough (offline
   sim, symbolic refs, no-deploy), or do user-specific constraints
   belong in the spec ("never touch the garden lights")?
4. **Status field**: does the spec carry its loop state (draft →
   approved → done), or is that loop metadata that lives beside it?
5. **Room metadata**: the house section needs more than name+type for
   real houses (room per device, maybe zones) — how much does v0.1
   carry before it becomes a house DB?
