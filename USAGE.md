# flua — user guide for QA developers

flua runs Fibaro QuickApps **offline** on your Mac or PC. You write the same
Lua you'd write on the HC3 — `QuickApp`, `fibaro`, `api`, `net`, `mqtt` — and
flua provides the rest of the world: a simulated HC3, real network access, a
virtual clock, a proper debugger with breakpoints, and a one-command path back
to the HC3 as a `.fqa` file.

The HC3 editor is tiny and debugging there means `print()` statements. flua
exists so you can develop in your real editor, with real tooling, and upload
when it works.

- [flua — user guide for QA developers](#flua--user-guide-for-qa-developers)
  - [Install](#install)
  - [Your first QuickApp](#your-first-quickapp)
  - [Running QAs](#running-qas)
  - [VS Code setup](#vs-code-setup)
    - [Without the repo (pip install)](#without-the-repo-pip-install)
  - [QA directives (`--%%`)](#qa-directives---)
    - [The Lua config file](#the-lua-config-file)
    - [The UI viewer](#the-ui-viewer)
  - [Multi-file QAs](#multi-file-qas)
  - [The offline HC3](#the-offline-hc3)
    - [Online mode — the real HC3](#online-mode--the-real-hc3)
  - [Loading QAs at runtime](#loading-qas-at-runtime)
  - [Network clients](#network-clients)
  - [Deploying to the HC3](#deploying-to-the-hc3)
  - [Bringing an HC3 QA home](#bringing-an-hc3-qa-home)
  - [Static checks](#static-checks)
  - [flua extensions (`_FLUA`)](#flua-extensions-_flua)

## Install

Python 3.11+. lupa (which bundles Lua) is the only runtime dependency.

```bash
pip install fibaro-flua        # from PyPI — installs the flua command
```

The PyPI page carries this guide in full. The wheel also ships the
`examples/` QuickApps — find where they are installed with:

```bash
flua --examples               # prints the directory; copy the examples out
flua --api local $(flua --examples)/timers.lua   # ...or run one in place
```

From a checkout (development):

```bash
cd flua
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
flua --version
```

## Your first QuickApp

A QuickApp is an ordinary Lua file. `QuickApp:onInit` runs exactly like on
the HC3, and `self:debug` prints immediately (unlike the HC3, where you'd
only see it in the debug window):

```lua
--%%name:hello
-- --------------- EOH ---------------
function QuickApp:onInit()
  self:debug("I started")
  setTimeout(function() self:debug("one second later") end, 1000)
end
```

Save it as `hello.lua` and run it:

```bash
.venv/bin/flua hello.lua
```

Every `.lua` file you pass is a QuickApp — it gets `QuickApp`, `fibaro`,
`api`, `net`, `mqtt`, timers, and runs `onInit` exactly like on the HC3.
Anything that has nothing left to do (no timers, no network connections)
makes flua exit; QAs with timers or open connections keep running.

## Running QAs

```bash
.venv/bin/flua script.lua              # one QA
.venv/bin/flua qa1.lua qa2.lua         # several QAs, isolated, can talk to each other
.venv/bin/flua -e 'setTimeout(function() print("hi") end, 100)'
.venv/bin/flua --run-for 5 script.lua  # at least 5 virtual s, then exit when idle
.venv/bin/flua --run-for -3 script.lua # exactly 3 virtual s
```

Virtual time — great for testing long-running logic (`--run-for` counts
virtual seconds: `--instant --run-for -5` runs five simulated seconds, and
an interval firing once per simulated second fires exactly five times):

```bash
.venv/bin/flua --speed 60 script.lua    # 60x faster
.venv/bin/flua --instant script.lua     # timers fire now, os.time() jumps ahead
```

`fibaro.sleep(ms)` suspends the *calling QA* for `ms` of virtual time — other
QAs keep running, and the sleep follows `--speed`/`--instant` like a timer.
Messages destined for the QA while it sleeps (timer callbacks, actions, UI
and network events) are queued and delivered, in arrival order, after the
sleeping callback resumes. It works anywhere in QA code — top level,
`onInit`, callbacks — because the QA identity is registered before the file
executes; only outside a QA (main-state code) does it raise an error.

## VS Code setup

The repo ships `.vscode/launch.json` with four configurations:

- **Flua: Run Current File** — runs the file in the panel.
- **Flua: Run Current File (Terminal)** — runs it in the integrated terminal
  (pick this one for `self:debug` output you can scroll).
- **Flua: Debug Current File (mobdebug)** — real debugging: breakpoints,
  stepping, variable inspection. Install the VS Code extension
  **Lua MobDebug** (`alexeymelnichuk.lua-mobdebug`), open your QA, press F5
  with the mobdebug configuration selected. flua waits for the debugger
  before running your code.
- **Flua: Debug Current File (UI+mobdebug)** — the same, plus the UI
  viewer server (`--ui 8090`): debug your QA while its UI is rendered in
  `viewer/index.html` (if 8090 is busy the server picks the next free port
  — point the viewer at the printed URL).

While you step through code, `print`/`self:debug` output appears **immediately**
— logs never queue behind a paused program.

The fastest loop for tinkering:

```bash
.venv/bin/flua --watch script.lua
```

flua restarts the QA whenever you save the file (or any `--%%file` file).
Ctrl-C stops it. Works on top of the debugger too.

### Without the repo (pip install)

Installed from PyPI you don't have this checkout's developer setup — the
VS Code run/debug configs, the Lua Language Server settings, and the agent
files (Copilot skills/instructions, `AGENTS.md`). One command scaffolds a
QA project directory with all of it:

```bash
flua --tool setup              # the current directory
flua --tool setup my-project/  # a project directory (created if missing)
```

It writes `.vscode/launch.json` (run in the panel, run in the terminal,
mobdebug, and mobdebug with the UI viewer), `.vscode/extensions.json`
(VS Code will offer to install the **Python**, **Lua MobDebug** and
**Lua Language Server** extensions),
`.luarc.json` (silences the HC3 globals for the language server), `AGENTS.md`
and the `.github/` skills, instructions and prompts. Existing files are
kept; `--force` overwrites.


## QA directives (`--%%`)

Directives are ordinary Lua comments at the top of the file. flua parses them
before running; the HC3 ignores them — the same file runs in both places.
Parsing stops at the end-of-header marker:

```lua
--%%name:my-qa
-- --------------- EOH ---------------
-- nothing below this line is parsed as a directive
```

| Directive | Meaning |
|---|---|
| `--%%name:x` | the device/QA name (`_FLUA.config.name`) |
| `--%%type:com.fibaro.binarySwitch` | device type (defaults to binarySwitch; unknown types are an error) |
| `--%%properties:value=false` | default device properties (plural form) |
| `--%%property:value=true` | raw property, scalar values; repeatable, merges |
| `--%%var:name=expr` | initializes a **QuickApp variable**; `expr` is a Lua expression — `'text'`, `42`, `{a=1}`, `config.color`, `os.getenv("X")` (one per line) |
| `--%%uid:...` | sets `quickAppUuid` |
| `--%%description:...` | sets `userDescription` |
| `--%%model:...` | sets `model` |
| `--%%build:7` | sets `buildNumber` (a number) |
| `--%%manufacturer:...` | sets `manufacturer` |
| `--%%file:lib.lua,lib` | extra QA file, loads before main (see below) |
| `--%%speed:60` | virtual time speed (global) |
| `--%%instant:true` | instant mode (global) |
| `--%%maxhours:48` | stop after 48 virtual hours (global) |
| `--%%time:speed=2,instant=true,hours=48,start=2027/10/6 12:00:20` | combined runtime settings (global) |
| `--%%time:2027/10/6 12:00:20` | bare form: set the virtual start time |
| `--%%u:{label="lbl",text="Status"}` | one UI row (see below); repeatable, order kept |
| `--%%useUiView:false` | render the legacy `viewLayout` instead of the new `uiView` (default true) |
| `--%%mode:offline` | pin this QA to the simulated HC3 (see below) |
| `--%%mode:online` | force this QA online against the real HC3 |
| `--%%mode:proxy` | proxy mode: mirror this QA onto the HC3 (online only, see below) |
| `--%%debug:refreshState=true,api=true,http=true` | debug logging: refreshStates events / `api.*` calls / `net.HTTPClient` requests (global) |
| `--%%debug:true` | shorthand for all three debug channels (`:false` disables them) |
| `--%%loglength:120` | debug line length cap (default 120) |
| `--%%warn:true` | extra runtime warnings for things the HC3 stays silent about (global) |
| `--%%db:house.json` | seed the simulated HC3 from a JSON file (devices, rooms, scenes, globalVariables, alarms, profiles) |
| `--%%db:+house.json` | seed **and** persist emulator state back to the file (see below) |
| `--%%location:latitude=59.33,longitude=18.07` | pin the sim's location (device 1's sunrise/sunset) — deterministic sun times without touching `.flua.lua` |

The legacy `--%%offline:true` and `--%%proxy:true` still work as aliases for
`--%%mode:offline` and `--%%mode:proxy` (an explicit `--%%mode` wins when
both appear).

### The emulator database (`--%%db`)

`--%%db:house.json` seeds the simulated HC3 from a JSON file — the same
schema as `examples/house.json` and the `--seed` flag (the directive wins
over `--seed`). `--%%db:+house.json` additionally persists emulator state
back to the file as it changes (atomic writes; the file must exist —
`echo '{}' > db.json` creates an empty one). What is persisted depends on
the mode, following each mode's source of truth:

- **offline** — the file *is* the house: devices, rooms, scenes,
  globalVariables, alarms and profiles, plus each QA's state (properties
  and quickAppVariables) and children, under a `qaState` section keyed by
  QA name.
- **online** — the real HC3 owns the house data; only the emulator's own
  artifacts are written back: `qaState` and `globalVariables`.
- **proxy** — everything worth keeping is already on the HC3; the `+` is
  ignored with a warning (seed still applies).

Running QAs are never persisted as devices — they are rebuilt from code each
run. Children survive restarts and re-register under their parent QA, so a
QA's usual `api.get("/devices?parentId="..self.id)` startup check finds
them. QA state is keyed by QA name (not the per-run id), so persisted state
is stable across runs; `--%%var` and the other property directives win over
persisted values. `internalStorage` (`self:internalStorageSet/Get`) is
persisted with the QA's state too — plugin variables survive runs like on
the HC3.

Names: `--%%name:value` for scalars,
`--%%name:sub1=val1,sub2=val2` for subparameters. A typo'd directive is
reported at runtime (a `unknown --%% directive` warning) and `flua --check`
flags it too.

### Debug logging

`--%%debug:refreshState=true,api=true,http=true` turns on per-category debug
logging (any subset; it is a global directive, so `.directives` can carry
it). `--%%debug:true` is shorthand for all three channels on:

- `refreshState=true` logs every refreshStates event flua sees in a short
  form — the event type plus the `id`/`deviceId`/`name`/`property`/`value`/
  `newValue` data fields that are present;
- `api=true` logs the QA's `api.*` and `api.hc3.*` calls as
  `api GET /devices/...`;
- `http=true` logs user `net.HTTPClient` requests — not the `api.*` calls.

`--%%loglength:120` caps the debug line length (default 120; a cut line ends
with `...`).

`--%%warn:true` turns on extra runtime warnings for things the HC3 never
complains about — starting with api error codes: when an `api.get`/`post`/
`put`/`delete` (or `api.hc3.*`) returns a 4xx/5xx — or a transport failure —
the emulator logs it, because most QA code silently ignores those status
codes. Flua's own log lines are visually distinct from QA logs: a `[FLUA]`
level column plus the QA tag the message belongs to:

```
[02.10.2026][17:32:41][FLUA   ][my-qa5000]: api GET /devices/9999 -> 404
```

### HTML in log messages

The HC3 console renders a small HTML subset in QA log lines; flua renders
it to the terminal as well — `print` and `fibaro.debug`/`trace`/`warning`/
`error` messages only (flua's own diagnostic lines are left alone):

- `<b>`/`<strong>`, `<i>`/`<em>`, `<u>` — bold, italic, underline
- `<font color="red">` / `<span style="color:blue">` — text color (named
  colors and `#rrggbb`)
- `<table>`/`<tr>`/`<td>`/`<th>` — a table with padded columns
- `<ul>`/`<ol>`/`<li>` — bullet / numbered lists
- `<br/>` — a line break
- anything else loses its tags, keeping the content

With colors on, formatting becomes ANSI; with `--color never` (or a
non-terminal) the tags are stripped instead, so the text stays readable.

### QuickApp UI (`--%%u`)

Each `--%%u:` line defines one row of the QuickApp UI; several elements can
share a row with `{{...},{...}}`. flua translates the rows into **both** UI
property structures the HC3 understands — the legacy `viewLayout` and the
new `uiView` — plus the `uiCallbacks` table that routes UI events to your
QuickApp methods. `useUiView` (default `true`) selects the new format:

```lua
--%%u:{label="statusLbl",text="Status: Ready"}
--%%u:{button="onBtn",text="Turn On",onReleased="turnOn"}
--%%u:{switch="autoSwitch",text="Auto Mode",value="false",onReleased="handleSwitch"}
--%%u:{slider="dimSlider",text="Brightness",min="0",max="100",value="50",onChanged="handleSlider"}
--%%u:{select="modeSelect",text="Mode",value="1",onToggled="handleSelect",
--      options={{type='option',text='Economy',value='1'},{type='option',text='Comfort',value='2'}}}
--%%u:{multi="tagMulti",text="Tags",values={"1","3"},onToggled="handleMulti",
--      options={{type='option',text='Tag A',value='1'}}}
--%%u:{{button="onBtn",text="On",onReleased="turnOn"},{button="offBtn",text="Off",onReleased="turnOff"}}
```

Elements: `label`, `button`, `slider`, `switch`, `select`, `multi`. Callbacks
(`onReleased`, `onChanged`, `onToggled`, …) name QuickApp methods; sliders
take `min`/`max`/`step`/`value`, selects and multis take `options` (each
`{type='option',text=…,value=…}`) plus `value`/`values`. Values in the
directive are Lua literals — strings need quotes, numbers and `true`/`false`
don't. Long rows may continue on following comment lines. At runtime the
device's `properties.viewLayout`, `properties.uiView`, and
`properties.uiCallbacks` hold the generated structures, and
`self:updateView(elm, prop, value)` updates them.

### The UI viewer

`flua --ui [PORT]` serves the simulated HC3 API over HTTP for the bundled
viewer (`viewer/index.html` in the repo) — open the page and point it at the
printed URL:

```bash
.venv/bin/flua --ui 8090 examples/ui.lua   # UI API on http://127.0.0.1:8090
open viewer/index.html                    # default base URL matches
```

The viewer polls `GET /devices`, renders `properties.uiView` (labels,
buttons, sliders, switches, single and multi selects — styled after the HC3
look), and sends interactions back through `GET /plugins/callUIEvent` — the
same contract the real HC3 UI uses, so your `onReleased`/`onChanged`/
`onToggled` methods fire exactly as on the controller. `self:updateView`
changes land live (the viewer merges `device.view` over the static
properties). The API server stays up after the QA's timers drain, so the
viewer keeps working while you tweak the file.

On top of the QA's own UI, the viewer renders the device type's **default
view** (the elements the HC3 adds itself): a binarySwitch gets a colored
TRUE/FALSE state label and Turn On/Turn Off buttons, a multilevelSwitch
adds a dimmer slider, sensors get a live value label, and so on — even when
the QA defines no `--%%u` directives at all. The viewer fetches them from
`GET /flua/embeddedUI` (a flua-only channel) and prepends them above the
custom UI; the elements are never stored in the device's `viewLayout`/
`uiView` properties, so they cannot leak into a .fqa export. Their controls
invoke device actions (`POST /devices/{id}/action/{name}`), and their
labels track the watched device properties (e.g. `value`), both exactly as
the HC3 client behaves. The definitions live in a table in
`src/flua/devices/uielements.py` — add a QA type there to give it a default
view.

For the *real* HC3 UI, use proxy mode instead (`--%%mode:proxy`): the mirror
QA on the HC3 renders the genuine UI and funnels every interaction back to
the emulated QA.

The virtual clock starts **now** unless you set a start time — handy for
testing dates: leap years, DST switches, New Year logic. Combine with
`--instant` to fast-forward through the interesting moments:

```bash
.venv/bin/flua --start "2027/12/31 23:59:50" script.lua
# or in the file: --%%time:start=2027/12/31 23:59:50,instant=true
```

### The Lua config file

`.flua.lua` (in the directory you run from, or `~/.flua.lua`; the legacy
`~/.plua/config.lua` also works) is Lua data, loaded once and merged into
`_FLUA.config` — handy for per-machine settings:

```lua
-- .flua.lua
return {
  user = "alice",
  pwd = os.getenv("HC3_PASSWORD"),   -- reads the .env chain
  colors = { "red", "green" },
}
```

QA code sees it as `_FLUA.config.user`, and `--%%var` expressions can use it:
`--%%var:color=config.colors[1]`. `--%%` annotations win over the file. A
faulty `--%%var` expression (a syntax error, indexing a nil key) is a
startup error — flua names the variable and exits 1 — but an expression
that evaluates to nil (`config.foo`, `os.getenv("MISSING")`) simply leaves
the variable unset.

A `location` table configures the simulated controller's location — device
1's `sunriseHour`/`sunsetHour` are computed from it:

```lua
return {
  location = { latitude = 59.3293, longitude = 18.0686 },  -- Stockholm
}
```

Precedence: the built-in default (Stockholm) < the db/seed file's
`location` < `.flua.lua` < `--%%location` (the main QA's directive) < a
runtime `PUT /settings/location`. Combine it with `--%%time:start=...` for
a fully deterministic sun: a known place on a known date.

`os.getenv(name)` reads through flua's environment chain: the local `.env`
in the directory you run from, then `~/.env`, then the shell environment.
Files are plain `KEY=value` lines (comments and quotes supported) and are
re-read when they change — handy for API tokens and per-machine settings
that don't belong in the QA code.

### The `.directives` defaults file

A `.directives` file in the directory you run from is read in as **defaults
for the main QA file**: the same `--%%` directive syntax as a QA header
(`-- --------------- EOH ---------------` stops parsing, full-line `#`
comments are ignored). A directive set in the QA itself overrides the file's
value — the `mode` family (`--%%mode`/`--%%offline`/`--%%proxy`) overrides
as a whole, so a QA can opt out of a default too.

```
# .directives — defaults for the main QA
--%%mode:offline      # this project normally runs offline
--%%description:local playground QA
```

This is the place for per-project defaults: run offline by default (and
override with `--%%mode:online` in a QA when you want the HC3), shared
names/descriptions, and log/trace defaults via `--%%debug`/`--%%loglength`.
Unknown directives in the file warn at runtime, like typos in QA headers.

## Multi-file QAs

On the HC3 a QA is a set of named Lua files — one is `main`. flua keeps your
files on disk and declares the extras in the main file:

```lua
--%%file:lib.lua,lib
--%%file:util.lua,util
-- --------------- EOH ---------------
print(helper())
```

Files load in declaration order, **main loads last**. Paths resolve relative
to the main file's directory. See `examples/multifile.lua`. The HC3's file
API works offline too (`api.get('/quickApp/' .. _FLUA.qaId .. '/files')` etc.).

## The offline HC3

### Online mode — the real HC3

The backend is picked from the **main QA's directives — its header merged
over the `.directives` defaults** (see below), before the engine starts:

1. an explicit `--api local|remote` always wins;
2. otherwise, `--%%mode:offline` in the **main** QA's directives selects
   the offline sim, `--%%mode:online`/`--%%mode:proxy` selects the real HC3;
3. otherwise, **online** — the default, which requires HC3 credentials in
   the environment (`HC3_URL`/`HC3_HOST`); without them flua exits with an
   error. The simulated HC3 is opt-in: `--api local` or `--%%mode:offline`.

`--%%mode:offline` on a *secondary* QA pins just that QA's `api.*` calls to
the sim while the rest of the run stays online — handy for keeping test QAs
sandboxed against a live controller. The legacy `--%%offline:true` is an
alias for `--%%mode:offline`.

With `--api remote`, the `api` table talks to the real HC3: everything your
flua QAs own (devices from 5000, seeded sim state) is served locally, and
anything the sim doesn't know is forwarded to the controller over HTTP —
the same Lua surface, hybrid routing. Credentials come from the .env chain:

```bash
# .env
HC3_URL=http://192.168.1.10/
HC3_USER=admin
HC3_PASSWORD=your-password
HC3_PIN=1111
```

```bash
.venv/bin/flua --api remote script.lua
```

Remote calls are synchronous (like on the HC3) — each `api.get` blocks the
QA for the HTTP round trip. **Credentials are never retried**: a 401/403
stops flua immediately with a warning, because the HC3 locks itself after
4 failed attempts. Wrong credentials = one attempt, then exit 1.

`api.hc3.get/post/put/delete` always targets the **real HC3 directly**,
bypassing the hybrid dispatch (this is what `fibaro.callhc3` uses, and it's
handy in test code that wants ground-truth data). Offline it stands in for
the simulated HC3.

### Proxy mode (`--%%mode:proxy`)

To test a QA against its real UI in the phone app — or against scenes and
other QAs on the controller — flua can deploy a **proxy QuickApp** on the
HC3 (the proxy concept). The QA keeps running in the emulator while a
proxy device named `<name>_Proxy` (same device type, same UI) runs on the
HC3, and the two are treated as one device:

```lua
--%%mode:proxy
```

- The emulated QA runs with the **proxy's HC3 id** — actions and UI events
  aimed at the proxy land in the emulator.
- The proxy funnels everything back: device actions are forwarded to
  `http://<your-ip>:<port>/api/devices/<id>/action/<name>` and UI events to
  `http://<your-ip>:<port>/api/plugins/callUIEvent`; the emulator runs them
  through the QA's `callAction`/UI callbacks exactly like a tap in the real
  UI.
- When the QA updates a property or a UI element (`self:updateProperty`,
  `self:updateView`, `self:setVariable`), flua pushes the same update to the
  HC3, so the proxy always reflects the emulated state.
- Property changes produce **one** refreshStates event: the HC3 proxy emits
  it and the poller mirrors it back — flua does not generate a second, local
  event.
- Children: `self:createChildDevice` creates them on the HC3, and children
  an existing proxy already has are shadowed in the emulator under their HC3
  ids at startup — the QA's `initChildDevices()` finds them, their property
  updates are stored locally and forwarded, and their actions/UI events route
  back through the proxy like the parent's. `api.delete(
  '/plugins/removeChildDevice/' .. id)` deletes a child on the HC3 and drops
  its emulated shadow (offline it just removes the local child).

An existing `<name>_Proxy` is reused (duplicates are deleted, the newest
wins; a proxy of the wrong device type is deleted and recreated). On reuse
flua refreshes the proxy's `viewLayout`/`uiView`/`uiCallbacks` from the QA's
current `--%%u` directives, so UI edits between runs show up on the
controller. `useUiView` is only pushed when the QA declares
`--%%useUiView` — otherwise the proxy keeps whatever you configured on the
HC3 (the legacy `viewLayout` still has features the new `uiView` lacks), and
a fresh proxy defaults to `true`. On startup flua tells the proxy where to
listen back through a `CONNECT` action, so an existing proxy always points
at the current emulator.

Proxy mode only works **online**: without HC3 credentials flua logs
`proxy disabled` and runs the QA offline as usual. A proxy QA also keeps
flua alive past idle (like `--%%keep-alive:true`) — it must stay up to serve
the proxy's callbacks.

The emulator listens for callbacks on all interfaces, port 8080 by default
(`FLUA_PROXY_PORT` in the .env chain overrides it; busy ports fall back to
the next free one). Your machine and the HC3 must be on the same network,
and your firewall must let the controller reach that port.

### Mode comparison

flua picks one of three modes per run: an explicit `--api local|remote` wins,
then the main QA's directives (`--%%mode:...`, merged over the `.directives`
defaults), then the default — `online`.

| Aspect | `offline` | `online` | `proxy` |
|---|---|---|---|
| Where the QA runs | in the emulator; device registered in the sim (id 5000+) | in the emulator; device registered in the sim (id 5000+) | in the emulator, under the proxy's HC3 id (same deviceID) |
| What exists on the HC3 | nothing | nothing | a `<name>_Proxy` QuickApp (same type and UI), deployed or reused |
| `api.*` routing | the sim only; unknown ids 404 | hybrid: sim entities locally, unknown ids forwarded to the HC3 | same hybrid; the QA's own device is the proxy id |
| `self:updateProperty` / `updateView` / `setVariable` / internal storage | sim updated, event posted locally | sim updated, event posted locally | sim AND the HC3 proxy updated; the event is posted by the HC3 — never duplicated locally |
| Children (`createChildDevice` / `removeChildDevice`) | created in the sim | created in the sim | created on the HC3 as children of the proxy and shadowed in the sim under their HC3 ids (existing proxy children are shadowed at startup; removal deletes both) |
| UI interactions | the local UI viewer | the local UI viewer | the HC3 phone app, through the proxy (actions and UI events are funnelled back to the emulator); the local viewer works too |
| Reached from the HC3 (scenes, other QAs) | no | no | yes — through the proxy device |
| `refreshStates` feed | events generated by the sim | sim events + real HC3 events mirrored through the long poll | same, and the proxy's own events arrive from the HC3 |
| House entities (global variables, custom events, rooms, sections, scenes) | created/updated in the emulator | created/updated in the emulator | created/updated in the emulator |
| `api.hc3.*` | stands in for the sim | the real HC3, directly | the real HC3, directly |
| HC3 credentials | not needed | required (`HC3_URL`/`HC3_USER`/`HC3_PASSWORD`) | required |

`api.get('/devices')` serves the **union** of the emulator's devices
(running QAs plus the seed) and the HC3's devices when online — the
emulated shadow wins on id clashes, so a proxy QA and its HC3 twin (same
deviceID) count once. An offline-pinned QA (`--%%mode:offline`) always sees
the sim only. Custom events, global variables and the other house entities
always live in the emulator in all three modes.

### Testing against the real HC3

Two opt-in suites, gated so a plain `pytest` never touches the controller
(set `HC3_TEST=1` and configure the credentials in the environment):

```bash
HC3_TEST=1 .venv/bin/pytest tests/test_hc3_live.py    # lifecycle: read-only + upload/call/delete
HC3_TEST=1 .venv/bin/pytest tests/test_hc3_compat.py  # shape oracle: sim vs real HC3
```

The lifecycle suite is production-aware: read-only checks (settings,
devices, globalVariables, refreshStates), one import of a test QA (its
startup, `fibaro.call` round-trip, and its refreshStates change feed are
verified), then deletion — only the test QA is ever touched. Wrong
credentials cost exactly one attempt (the lockout guard).

The compat suite runs the same requests through the offline sim and the
real HC3 and diffs the response shapes: type mismatches and fields the sim
serves that the HC3 doesn't are failures; fields the sim doesn't model yet
are reported as gaps.

`RefreshStateSubscriber` (the refreshStates subscriber class) works in
both modes: offline, sim state changes (property updates, actions) are
emitted as real-shaped `DevicePropertyUpdatedEvent` /
`DeviceActionRanEvent` events — `updateProperty` only emits when the value
actually changes — and online, the poller long-polls the real HC3's
refreshStates and mirrors its events into the same feed. Both arrive at
subscribers through the message pump as a `refreshStateEvent` message.

The poller never keeps flua alive by itself: online runs still exit when no
timers, messages, or connections are pending. A QA that must keep running
past idle — waiting for HC3 events like it would on the controller — opts in
with a directive:

```lua
--%%keep-alive:true
```

While a loaded keep-alive QA is running, flua holds the HC3's long poll and
stays up until the QA exits (or Ctrl-C; a fixed `--run-for -5` also works);
without the directive the poller still mirrors events for the running QAs,
but never holds the process open — a drained run exits promptly. Ctrl-C
always terminates flua immediately, even mid-long-poll, and exits with
status 130.

`--seed` loads a simulated house (see `examples/house.json`):

```bash
.venv/bin/flua --seed examples/house.json script.lua
```

Your QAs become devices (ids from 5000) in the same simulated HC3, so
everything works between them:

- `api.get/post/put/delete` — the real HC3 REST surface (devices, plugins,
  variables, globals, scenes, alarms, profiles, refreshStates, …)
- `fibaro.call(id, 'turnOn')` — calls another QA's QuickApp method
- `fibaro.emitCustomEvent(name)` → `QuickApp:onCustomEvent(name)` handlers
- `self:setVariable/getVariable` — persistent, survives restarts
- `plugin.restart(id)` — re-runs the QA's code (onInit runs again, like the
  HC3 restarting the plugin); timers are cancelled and deferred messages
  dropped
- `GET /refreshStates?last=N` — the HC3's polling change feed

QAs find each other by name with `fibaro.getIds({type = "quickApp"})` — see
`examples/qa3.lua` and `examples/qa4.lua` calling each other.

## Loading QAs at runtime

From VS Code you often run one QA — let it bring up the QAs it needs:

```lua
local id = _FLUA.loadQAfromFile("examples/qa3.lua")   -- annotations parsed
local id2 = _FLUA.loadQAfromString([[ ...inline QA... ]])
local id3 = _FLUA.loadQAfromFile(                      -- extra directives
  "examples/qa3.lua",
  { "var:friend=42", "property:value=true" }
)
fibaro.call(id, "turnOn")   -- immediately reachable
```

The optional second argument is a table of directive strings, applied as if
appended to the loaded QA's `--%%` header: `var`/`property` merge per key
(the QA's own variables survive), `u`/`file` append, everything else
overrides. Both functions return the new QA id (or `nil, error`).
`examples/dynamic.lua` demos it.

## Network clients

Real network, HC3-style APIs, all asynchronous through the pump (callbacks
run in your QA, timers keep running while requests are in flight):

- `net.HTTPClient()` → `request(url, {options, success, error})` — `examples/http.lua`
  (`options.checkCertificate = false` skips HTTPS certificate verification,
  like the HC3 — handy for self-signed certs; the default verifies)
- `net.TCPSocket({timeout=ms})` → `connect/send/read/readUntil/close` — `examples/tcp.lua`
- `net.UDPSocket({broadcast, timeout})` → `sendTo/receive` — `examples/udp.lua`
- `net.WebSocketClient()/WebSocketClientTls()` → `addEventListener`, `connect`, `send`, `sendBinary` — `examples/websocket.lua` (`connect(url, headers)` takes a headers table, like the HC3; `sendBinary` sends binary frames, and `dataReceived(payload, isBinary)` receives them — the new HC3 binary mode)
- `mqtt.Client.connect(uri, options)` → `subscribe/publish/unsubscribe/disconnect`, `mqtt.QoS` — `examples/mqtt.lua`

TCP/UDP payloads are **binary-safe**: raw bytes (including NUL and values
above 0x7F) cross the bridge byte-for-byte in both directions — a payload
is escaped for the message bridge and un-escaped on the wire, so even a
literal `\x` sequence in your data round-trips intact.

## Deploying to the HC3

```bash
.venv/bin/flua export script.lua -o myqa.fqa
```

Upload `myqa.fqa` through the HC3 web UI (Create QuickApp → import). The
package follows the HC3's schema — only the properties the HC3 accepts
travel; dynamic properties are left out.

Or let flua talk to the HC3 directly with the `--tool` (alias `-t`)
commands — they package/unpack for you, so you develop in the unpacked
format (individual `.lua` files) and only the HC3 sees `.fqa`:

```bash
# upload an unpacked project (main file + --%%file extras) as a new QA
.venv/bin/flua --tool uploadQA script.lua            # --room ID to place it

# update an existing QA's files from the unpacked project
.venv/bin/flua --tool updateQA 123 script.lua

# download a QA from the HC3 and unpack it into individual .lua files
.venv/bin/flua --tool downloadQA 123 -d project/     # -d DIR (default: QA name)

# build an offline db from the real HC3 (device 1, location, family locations)
.venv/bin/flua --tool createDB -o db.json            # -f to overwrite

# scaffold a QA project: .vscode configs + agent skills/instructions
.venv/bin/flua --tool setup [project-dir]

# list the installed tools (a bare --tool, or --tool help)
.venv/bin/flua --tool
```

A download names every file `<QA-name>_<file>_<id>.lua` (the QA name is
sanitized for the file system) — `My QA_main_123.lua` for the main,
`My_QA_lib_123.lua` for extras — so several QAs can live in one directory
without colliding, and the HC3 id travels with the files. The generated main
regenerates the QA's header from the package: its UI comes back as `--%%u`
rows (translated from `uiView`/`viewLayout`/`uiCallbacks`), variables as
`--%%var` lines — and any old `--%%` directives in the downloaded code are
dropped, since they may be outdated. `uploadQA` then takes either the QA
name (it finds the project in the current directory) or the fully qualified
`<QA-name>_main_<id>.lua` and updates that QA on the HC3; a plain
`main.lua` uploads as a new QA.

The tools need HC3 credentials (the `.env` chain, like online mode).
`uploadQA` prints the new device id; `updateQA` puts all files at once;
`downloadQA` writes a `main.lua` with the QA's directives plus the extra
files — a normal flua project.

## Bringing an HC3 QA home

Export the QA from the HC3 UI (`.fqa`), then:

```bash
.venv/bin/flua unpack myqa.fqa -d myqa-project/
```

You get a runnable flua project: `main.lua` with generated `--%%` directives
and one file per QA file, ready for editing and debugging.

## Static checks

```bash
.venv/bin/flua --check script.lua
```

Checks syntax, unknown `--%%` directives (typos), and deprecated API calls.
Warnings don't fail the run; syntax errors exit 1. Good in CI.

## The HC3 REST API reference

`docs/specs/hc3-api.json` is the checked-in structural reference of the HC3
REST API — endpoints (method, path, parameters with types, request-body
schemas, response status codes) and schema field names/types. It is
distilled from the official swagger, which is Fibaro's property and not
distributed: the local copy (`fibaro_api_docs/`, gitignored) is only needed
when regenerating the reference:

```bash
.venv/bin/python scripts/extract_hc3_api.py
```

## flua extensions (`_FLUA`)

Everything HC3-compatible is a plain global (`QuickApp`, `fibaro`, `api`,
`net`, `mqtt`, `json`, …). flua-specific helpers live on `_FLUA` so your code
stays portable:

- `_FLUA.qaId` — this QA's id; `_FLUA.config` — this QA's config table
- `_FLUA.arg` — the file path / `-e` marker
- `_FLUA.exit(code)` — stop the engine (vs `exit(code)` which stops only this QA)
- `_FLUA.qa(id)` — another QA's QuickApp instance (lupa proxy)
- `_FLUA.loadQAfromFile(path, directives?)` / `_FLUA.loadQAfromString(code, directives?)` — dynamic QA loading; `directives` is an optional table of directive strings added to the loaded QA's config
- `_FLUA.async.run(fn)` / `_FLUA.async.await(worker)` / `_FLUA.async.wait(ms)` — coroutine awaits
- `_FLUA.millitime()` — virtual time in whole milliseconds (sub-second timing; `os.time()` is whole seconds, `os.clock()` is real CPU time)
- `_FLUA.setTimeout(fn, ms, qaId)` — timer with explicit QA attribution
- `if _FLUA then` — detect flua at runtime