# 06 · On the real HC3

The lamp has lived its whole life in a simulation on your computer. This
chapter moves it into your real HC3 — the same file, unchanged. That's the
flua promise: **what you tested at home is what runs on the controller.**

## Before you start

Three small things, all done or known from earlier chapters:

- Your HC3 and your computer are on the same network.
- The `.env` file from chapter 01 (step 6) holds the HC3's address and your
  credentials.
- You know which light is *safe to play with* — pick a real lamp you can
  watch, and make sure turning it on and off is harmless (nobody is in the
  shower on its circuit).

> A note on honesty: everything in this chapter up to the upload is exactly
> what flua does; the upload commands themselves talk to *your* controller,
> which this tutorial can't rehearse for you. They are the tool's documented
> behavior, and they print what they do. If anything looks different, the
> next chapter teaches you how to read the situation.

## Step 1 — a dress rehearsal against your real house

So far the lamp has run in the simulated world (offline is flua's default).
For the dress rehearsal, tell the lamp to go **online** with a mode
directive in its header — `--%%mode:online` — or pass `--api remote` on the
command line. Your QuickApp still runs on your computer, but every question
it asks the HC3 — `fibaro.getValue(1, "sunsetHour")`, `api.get(...)`,
everything — is answered by your **real** controller:

```bash
flua --api remote --start '2026/10/4 18:30:00' sunset_lamp_ui.lua
```

```text
🚀 flua 0.1.12 (Lua 5.5, Python 3.14.3), mode online
[04.10.2026][18:30:00][DEBUG  ][SunsetLamp5000]: Sunset lamp ready, 60 W
```

The sunset hour now comes from your actual HC3 and location, not the
simulation's Stockholm default. Nothing is deployed, nothing is changed on
the controller — the lamp is just *consulting* it. Press `Ctrl-C` when
you've seen enough.

(If flua refuses to start and complains about credentials, your `.env` is
missing or the address/password is wrong — flua exits on the first failed
login attempt on purpose, because the HC3 locks itself after four.)

## Step 2 — upload the lamp

One command puts the lamp onto the controller:

```bash
flua --tool uploadQA sunset_lamp_ui.lua
```

```text
uploaded SunsetLamp — HC3 device id 123
```

(`123` will be *your* HC3's next free device id.) The tool packages the QA —
your `--%%` header becomes the device's name, type, UI and variables — and
creates the device on the HC3. Open the Fibaro app on your phone: the
SunsetLamp is there, a real switch with your **Automatic** toggle below the
On/Off buttons.

**The first real test:** tap **Turn On** in the app. The light comes on.
That's your action running on the HC3, exactly as it ran in the viewer.
Welcome to home automation.

## Step 3 — fix it, update it

Found something to improve? Edit the file, then update the QA in place (the
device id is the one uploadQA printed):

```bash
flua --tool updateQA 123 sunset_lamp_ui.lua
```

If you didn't note the id: `flua --tool downloadQA` fetches a QA into a
project folder whose file names carry the id —

```bash
flua --tool downloadQA 123 -d lamp/
# lamp/SunsetLamp_main_123.lua  (the id travels with the file name)
flua --tool updateQA lamp/SunsetLamp_main_123.lua   # updates QA 123
```

so a downloaded QA is always re-uploadable, even weeks later.

New QAs can land directly in a room:

```bash
flua --tool uploadQA --room 5 sunset_lamp_ui.lua
```

(`5` is the room's id — visible in the HC3 app's room settings.)

## The other direction: bringing an HC3 QA home

The HC3 app can export any QuickApp as an `.fqa` file. flua can unpack that
file into a normal flua project — so QAs you wrote on the controller can
live on your computer too:

```bash
flua unpack myqa.fqa -d myqa-project/
```

```text
unpacked to myqa-project/ (main: myqa-project/main.lua)
```

```bash
flua export sunset_lamp_ui.lua -o lamp.fqa
```

```text
exported 1 files to lamp.fqa
```

`unpack` regenerates the `--%%` header from the package (name, type, UI
rows, variables), so you can read exactly how the device was configured —
and `export` produces a package another HC3 owner could install from the
app. Both directions are open.

## What did we just learn?

- The **same file** runs in the simulation, consults your real HC3, and
  finally lives **on** it — flua never rewrites your code between worlds.
- `--tool uploadQA` deploys; `updateQA` updates; `downloadQA`/`unpack`/
  `export` move QAs in both directions.

Next chapter: when it doesn't go as planned — reading the log, checking
your work before running it, and debugging like a grown-up.
