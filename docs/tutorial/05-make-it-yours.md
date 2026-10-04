# 05 · Make it yours

Until now the lamp's interface was the two buttons the HC3 gives every
switch. This chapter adds **your own** control panel: a switch that turns
the automatic mode on and off, and a label that says what the lamp is
doing. You'll also give the lamp its first **quickApp variable** — a value
you can change later from the HC3 app without touching the code.

## The lamp with a control panel

Save this as `sunset_lamp_ui.lua` (or use the repo's copy at
`examples/sunset_lamp_ui.lua`):

```lua
--%%name:SunsetLamp
--%%type:com.fibaro.binarySwitch
--%%var:auto=true
--%%var:wattage=60

--%%u:{label="status",text="Automatic mode"}
--%%u:{switch="automatic",text="Automatic",value="true",onReleased="toggleAuto"}
-- --------------- EOH ---------------

function QuickApp:onInit()
  self:debug("Sunset lamp ready,", self:getVariable("wattage"), "W")
  self:checkSun()
  setInterval(function() self:checkSun() end, 60 * 1000)
end

function QuickApp:turnOn()
  self:updateProperty("value", true)
  print("Lamp on")
end

function QuickApp:turnOff()
  self:updateProperty("value", false)
  print("Lamp off")
end

function QuickApp:toggleAuto(e)
  local auto = e.values and e.values[1] == "true"
  self:setVariable("auto", auto)
  self:updateView("status", "text", auto and "Automatic mode" or "Manual mode")
  if auto then self:checkSun() end
end

function QuickApp:checkSun()
  if not self:getVariable("auto") then return end -- manual mode: hands off
  local now = os.date("*t")
  local h, m = fibaro.getValue(1, "sunsetHour"):match("(%d+):(%d+)")
  local sunsetMin = tonumber(h) * 60 + tonumber(m)
  local nowMin = now.hour * 60 + now.min
  if nowMin >= sunsetMin and not self.properties.value then
    self:turnOn()
  elseif nowMin < sunsetMin and self.properties.value then
    self:turnOff()
  end
end
```

### Your own UI: the `--%%u` lines

The two new header lines describe the panel:

```lua
--%%u:{label="status",text="Automatic mode"}
--%%u:{switch="automatic",text="Automatic",value="true",onReleased="toggleAuto"}
```

Each `--%%u` line is one row of your QuickApp's own UI:

- a **label** named `status`, showing "Automatic mode";
- a **switch** named `automatic`, starting ON (`value="true"`). When someone
  flips it, the QuickApp's `toggleAuto` action runs (`onReleased`).

That's the whole recipe for HC3 interfaces: rows of `label`, `button`,
`switch`, `slider`, `select` — each with a name and the action to call. The
HC3 app renders the same rows on the real controller later.

### Reacting: `toggleAuto`

```lua
function QuickApp:toggleAuto(e)
  local auto = e.values and e.values[1] == "true"
  self:setVariable("auto", auto)
  self:updateView("status", "text", auto and "Automatic mode" or "Manual mode")
  if auto then self:checkSun() end
end
```

Two new tricks:

- **UI actions receive an event.** `e.values[1]` is what the user did — a
  switch delivers `"true"` or `"false"`. The lamp stores it in a
  **variable** named `auto` (see the next section for why a variable and
  not a property).
- **`self:updateView(...)`** changes a piece of your UI: the `status` label
  now reads "Manual mode" — or "Automatic mode" again when switched back.
  This is how QuickApps talk to their own panels.

And the guard at the top of `checkSun`:

```lua
if not self:getVariable("auto") then return end
```

In manual mode the lamp leaves the light alone — the user has taken over.
`return` means "stop this function right here".

### QuickApp variables: `--%%var`

Both header lines starting with `--%%var` give the lamp **variables** —
named values that live *with* the QuickApp:

```lua
--%%var:auto=true
--%%var:wattage=60
```

- `wattage` is a value you might tweak later — on the real HC3 you can
  edit variables in the app (device settings) without changing any code.
- `auto` is the lamp's **memory**: whether the automatic mode is on.
  `toggleAuto` writes it with `self:setVariable("auto", …)` and `checkSun`
  reads it with `self:getVariable("auto")`.

Why a variable and not a property? A QuickApp's properties are **fixed by
its type**: a `binarySwitch` has `value`, and that's the schema — you can't
invent an `auto` property for it. (`self:updateProperty("value", …)` from
chapter 03 works because `value` is in the schema.) Variables, on the
other hand, are free-form, and — the real reason `auto` is one — they
**survive restarts**: when the HC3 (or flua) restarts the QuickApp, the
variables keep their values, so the user's switch choice isn't lost. The
`--%%var:auto=true` line only sets the *starting* value, the first time.

## Run it and flip the switch

Press **F5** with the **Flua: Run Current File (UI)** configuration, as in
chapter 03, and open **http://127.0.0.1:8090/**.

```text
flua: UI viewer on http://127.0.0.1:8090/ — open it in a browser
🚀 flua 0.1.12 (Lua 5.5, Python 3.14.3), mode offline
[04.10.2026][21:00:00][DEBUG  ][SunsetLamp5000]: Sunset lamp ready, 60 W
[04.10.2026][21:00:00][DEBUG  ][SunsetLamp5000]: Lamp on
```

If the lamp *didn't* turn on: it's daytime where your virtual clock thinks
it is (F5 starts at the real time, like chapter 04). Pin the sun with
chapter 04's trick instead:

```bash
flua --api local --ui 8090 --start '2026/10/4 18:30:00' sunset_lamp_ui.lua
```

Open the viewer (chapter 03) and press **Connect**.

> ✅ **You should see** the panel from before — On/Off and the state label —
> and *below* it, your own rows: the status label and the **Automatic**
> switch, sitting ON.

Now flip **Automatic** off.

> ✅ **You should see** the status label change to `Manual mode` — your
> `toggleAuto` action ran, stored `auto=false`, and updated the label.

And because it's past sunset in the virtual world, flip the lamp off and on
with **Turn Off / Turn On** — manual mode means the lamp won't fight you:
`checkSun` returns immediately and leaves the light exactly where you put
it. Flip **Automatic** back on and watch it take over again.

Press the red square (■) in VS Code's Run toolbar when you're done.

## What did we just learn?

- **`--%%u` rows** build your QuickApp's own UI — labels, buttons, switches,
  sliders, selects — each calling one of your actions.
- **UI actions receive the event** (`e.values`), so they know what the user
  did.
- **`updateView`** lets the QuickApp change its own UI live.
- **QuickApp variables** (`--%%var`, `getVariable`/`setVariable`) are
  free-form values that live with the device — tweakable settings, and
  state that survives restarts (a QA's properties are fixed by its type).

Next: the lamp has been living in a simulation this whole time. Time to
move it into your real HC3.
