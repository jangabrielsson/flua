# 04 · The house comes alive

The lamp switches when *you* press the button. This chapter makes it switch
**by itself**: every minute it asks "is the sun down yet?" and turns on when
the answer changes to yes. Along the way you meet the two ideas that make
QuickApps feel alive — **timers** and **time**.

## The lamp that checks the sun

Save this as `sunset_lamp_auto.lua` (or use the repo's copy at
`examples/sunset_lamp_auto.lua`):

```lua
--%%name:SunsetLamp
--%%type:com.fibaro.binarySwitch
-- --------------- EOH ---------------

function QuickApp:onInit()
  self:debug("Sunset lamp ready")
  self:checkSun()
  setInterval(function() self:checkSun() end, 60 * 1000) -- once a minute
end

function QuickApp:turnOn()
  self:updateProperty("value", true)
  print("Lamp on")
end

function QuickApp:turnOff()
  self:updateProperty("value", false)
  print("Lamp off")
end

function QuickApp:checkSun()
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

Four new ideas, each worth a moment:

**1. Timers.** `setInterval(function() … end, 60 * 1000)` runs the block
every 60 000 milliseconds — one minute. This is how a QuickApp "does
nothing, most of the time": it's just waiting for its timers.

**2. The HC3 knows the sun.** `fibaro.getValue(1, "sunsetHour")` — device
number **1 is the HC3 itself**, and the HC3 can answer questions about your
house: when the sun sets (`"18:13"`), when it rises, your location. Your
QuickApp asks the controller instead of doing astronomy.

**3. The clock.** `os.date("*t")` returns the current date and time as a
small table: `now.hour`, `now.min`, … The lamp turns both times into
"minutes since midnight" (`hour * 60 + min`) so it can compare them with a
plain `>=`.

**4. Only change things when they must change.** The two `if`s make sure the
lamp only acts when the state is wrong — otherwise it would call `turnOn`
every single minute, forever. QuickApps should be gentle like this; the
HC3 logs everything.

The two actions from last chapter are still there, unchanged — the lamp can
now be switched **by the sun and by hand**, because both paths go through
the same two functions.

## Run it after sunset

```bash
flua --api local --start '2026/10/4 18:30:00' sunset_lamp_auto.lua
```

```text
🚀 flua 0.1.12 (Lua 5.5, Python 3.14.3), mode offline
[04.10.2026][18:30:00][DEBUG  ][SunsetLamp5000]: Sunset lamp ready
[04.10.2026][18:30:00][DEBUG  ][SunsetLamp5000]: Lamp on
```

> ✅ **You should see** the lamp turn itself on at boot — 18:30 is after
> sunset (18:13), so `checkSun` finds the lamp off and switches it on.

Press `Ctrl-C` to stop it. (Without `Ctrl-C` the lamp would run until you
stop it — it's waiting for its next minute, after all.)

**What's `--start`?** flua keeps its own clock — the **virtual clock** —
separate from your computer's. `--start` sets it: the QuickApp above truly
believes it is October 4th 2026, 18:30, and every log line is stamped with
*that* time. That's how you test winter darkness in July, New Year's Eve in
March, or — as we're about to do — a whole evening in seconds.

## Fast-forward to the sunset

Here's the magic for the impatient. Start the lamp at 18:00, **before**
sunset, and let flua fast-forward time for you:

```bash
flua --api local --start '2026/10/4 18:00:00' --instant --max-hours 1 sunset_lamp_auto.lua
```

```text
🚀 flua 0.1.12 (Lua 5.5, Python 3.14.3), mode offline
[04.10.2026][18:00:00][DEBUG  ][SunsetLamp5000]: Sunset lamp ready
[04.10.2026][18:13:00][DEBUG  ][SunsetLamp5000]: Lamp on
flua: virtual time limit reached (1.0h)
```

Read the timestamps: the lamp started at 18:00 — correctly decided *not* to
turn on — and then time **jumped minute by minute** until 18:13, when it
turned itself on at exactly the sunset the HC3 had calculated. A whole
evening of lamp logic, tested in under a second.

The two flags:

- `--instant` — timers fire immediately, and virtual time jumps ahead by
  each delay instead of waiting. A one-minute interval becomes "check the
  sun, jump a minute, check again…"
- `--max-hours 1` — a safety leash: stop after 1 virtual hour. Without it,
  an instant lamp would check minutes until the end of time (instantly).

There's also `--speed 60` for "60 times faster than real life" — same idea,
but you watch it run.

> ✅ **You should see** `Lamp on` stamped `18:13:00` — the sunset from the
> `sunsetHour` calculation, to the minute.

## What did we just learn?

- **Timers** are how a QuickApp wakes itself up: `setInterval(fn, ms)`.
- **The HC3 is a device too** — device 1 — and it answers questions like
  "when is sunset?" through `fibaro.getValue(1, …)`.
- **flua's virtual clock** lets you test *any* time instantly: `--start`
  sets it, `--instant`/`--speed` fast-forward it, `--max-hours` bounds it.

Next: the lamp grows a control panel of its own — a switch that turns the
automatic mode on and off, right next to the On/Off buttons.
