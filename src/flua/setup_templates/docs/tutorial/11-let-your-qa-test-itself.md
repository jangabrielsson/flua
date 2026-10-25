# 11 · Let your QuickApp test itself

Every chapter so far ended the same way: run the QA, look at the log, nod.
That loop is perfect while you're learning — and it quietly falls apart the
moment the QA grows. Change one line in a hundred-line file, and the log
looks *almost* the same. Did the lamp still turn on at sunset? You'd have to
watch it to know.

This chapter teaches the lamp to check **itself**. A small test file sits
next to it, runs the same offline sim you already know, and answers with one
word: pass or fail.

## Step 1 — the test file

Create `sunset_test.lua` in your project folder:

```lua
--%%name:sunset_test
local Test = require("flua-test")
local t = Test.new()

-- the lamp's own logic: turnOn must light it
function QuickApp:turnOn()
  self:updateProperty("value", true)
end

function QuickApp:onInit()
  -- 1. the sim is honest: the device exists, under the id the QA sees
  local dev = api.get("/devices/" .. _FLUA.qaId)
  t:expect(dev.name == "sunset_test", "the device answers by name")
  t:assert_eq(dev.id, _FLUA.qaId, "the id matches")

  -- 2. our own logic, checked against the sim
  self:turnOn()
  t:expect(self.properties.value == true, "turnOn lights the lamp")

  t:finish()
end
```

Three new names, all from flua's built-in test library:

- `require("flua-test")` loads it — no download, nothing to install.
- `t:expect(condition, "message")` checks one thing and prints `PASS:` or
  `FAIL:`.
- `t:finish()` prints the failure count and ends the run with it — so the
  *exit code* says pass or fail, not your eyes.

You already know the rest: `api.get` is the sim (chapter 02),
`updateProperty` is how the lamp changes its own state (chapter 03), and
`function QuickApp:turnOn()` is the lamp's action (chapter 03 again).

## Step 2 — run the suite

One command runs every `*_test.lua` file in the folder:

```bash
flua test
```

```text
  PASS  sunset_test.lua
flua test: 1 passed, 0 failed, 0 timed out
```

> ✅ **You should see** `PASS  sunset_test.lua`.

`flua test` finds the test files by name (anything ending in `_test.lua`),
runs each in its own fresh sim — so tests can't trip over each other — and
exits 0 only when everything passes. That last part matters more than it
looks: chapter 07's agents, and any computer, can now check your lamp
without reading a single log line.

## Step 3 — break it, on purpose

Make the lamp's check wrong:

```lua
t:expect(self.properties.value == false, "turnOn lights the lamp")
```

Run the suite again:

```text
  FAIL  sunset_test.lua  (failures: 1)
flua test: 0 passed, 1 failed, 0 timed out
```

> ✅ **You should see** `FAIL` and `failures: 1`.

Put the line back. This is the whole point: the test catches the mistake
*now*, while you're two minutes from it — not after it has lived on your
HC3 for a week.

## Step 4 — the test that never ends

A test QA must end itself with `t:finish()`. Forget that — say you delete
`t:finish()` and leave a repeating timer running — and the runner doesn't
hang your machine: it waits a while, then reports:

```text
  TIME  sunset_test.lua  (no exit within 5s — does the test end with t:finish()/exit(...)?)
```

(To see it: delete the `t:finish()` line and add
`setInterval(function() end, 1000)` somewhere, run `flua test --timeout 5`,
then put both back.)

## What did we just learn?

- `require("flua-test")` + `t:expect`/`t:assert_eq`/`t:finish()` — a test
  file is just a QA that checks things and exits with the failure count.
- `flua test` finds `*_test.lua` files, runs them isolated, and reports
  `PASS`/`FAIL`/`TIME` — exit code 0 means everything holds.
- Tests run offline against the sim, so they are fast, free, and safe to
  run constantly.
- The assertions can even travel to the real HC3 — declare the library as a
  QA file (`--%%file:$flua-test.lua,flua_test`, the chapter-09 move) and the
  same test code turns into no-ops on the controller.

## Where you are now

That's the whole loop: write, run, look — and now *prove*. The lamp checks
itself, the suite says so in one line, and every future change gets checked
for free.

The rest is practice, the flua thread on the Fibaro forum, and the manual
(`USAGE.md`) for everything this tutorial deliberately skipped — record and
replay of your real house, the coverage audit, the VS Code extension's
toolbox. Happy automating — and mind the sunset.
