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

`flua --version --machine` prints one JSON line instead
(`{"version", "lua", "python"}`) — the stable capability probe for agents,
installers, and scripts.

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
.venv/bin/flua --run-for 5 script.lua  # at least 5 virtual s, then exit when idle —
                                        # but never past 5 WALL s (a hard deadline:
                                        # an open SSE stream or keep-alive QA can't
                                        # keep the run alive past it)
.venv/bin/flua --run-for -3 script.lua # exactly 3 virtual s
.venv/bin/flua -D mode:online -D var:x=42 script.lua
                                        # inject directives as if appended to
                                        # the QA's header — test foreign code
                                        # without editing it (repeatable; the
                                        # injected lines win over the file's)
```

`.flua-directives`, a file in the main QA's directory, is the file-based
spelling of `-D` — same `--%%` syntax, discovered automatically (see
[below](#the-flua-directives-override-file)), so a VS Code F5 run picks it
up with no launch.json edits. Precedence: the QA's header < its
`--%%include` defaults < `.flua-directives` < `-D` flags.

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

The repo ships `.vscode/launch.json` with five configurations (the
`--tool setup` template has the same five, with the debug interpreter
resolved to flua's **absolute path** — VS Code doesn't inherit the shell's
PATH on macOS, so a bare `flua` would not be found; the run configurations
use the selected Python interpreter), all running with `--api local` — the
offline playground):

- **Flua: Run Current File** — runs the file in the panel.
- **Flua: Run Current File (Terminal)** — runs it in the integrated terminal
  (pick this one for `self:debug` output you can scroll).
- **Flua: Run Current File (UI)** — runs it and serves the UI viewer at
  `http://127.0.0.1:8090/` (if 8090 is busy the server picks the next free
  port — open the printed URL).
- **Flua: Debug Current File (mobdebug)** — real debugging: breakpoints,
  stepping, variable inspection. Install the VS Code extension
  **Lua MobDebug** (`alexeymelnichuk.lua-mobdebug`), open your QA, press F5
  with the mobdebug configuration selected. It uses the project venv's
  `flua` executable on macOS and `flua.exe` on Windows. flua waits for the
  debugger before running your code.
- **Flua: Debug Current File (UI+mobdebug)** — the same, plus the UI
  viewer server (`--ui 8090`): debug your QA while its UI is rendered at
  `http://127.0.0.1:8090/`.

While you step through code, `print`/`self:debug` output appears **immediately**
— logs never queue behind a paused program.

The flua CLI writes stdout and stderr as UTF-8 on all platforms, including
when a debugger captures output through pipes on Windows. This preserves
Unicode text and the startup rocket in VS Code's debug console.

**Lua Language Server support**: the repo's `.luarc.json` declares Lua 5.4
with the HC3 globals and loads the bundled **`.luals/` type library** — LuaLS
definitions for `QuickApp`, `fibaro`, `api` and `json` — so QA code in the
repo gets autocomplete and parameter hints. `flua --tool setup` ships the
same configuration (and the type library) into scaffolded projects for pip
users; the two copies are kept byte-identical by a test.

### The flua VS Code extension

The repo also ships the **flua VS Code extension** (`vscode/`) — the
explorer drives flua without touching launch.json:

- Right-click a file → **flua**: pack a QA into a `.fqa`, unpack a `.fqa`
  into a project, upload a file / a new QA / an updated QA to the HC3,
  download a QA, scaffold a QA from the 30 type templates, or run
  `--tool setup`.
- **Check on save**: saving a `.lua` file runs `flua --check --json`;
  syntax errors, unknown `--%%` directives, plua-style directive typos,
  and deprecated REST endpoints appear in the Problems panel (findings
  for `--%%file` includes land on those files).
- `.fqa` packages open in the **flua QA editor**: the package summary
  (name, type, interfaces) plus the packed metadata (properties like
  `manufacturer`/`userDescription`, `quickAppVariables` one per line, and
  a collapsed UI summary) and a Lua preview per file with Unpack/Upload
  buttons; the raw JSON stays available via "Reopen Editor With… Text
  Editor" (validated against flua's package schema).

The extension only shells out to the `flua` executable — auto-detected
from a workspace `.venv`, else `flua` on PATH, else the `flua.executable`
setting. Tools run in the shared flua terminal so interactive HC3
credential prompts work. Install it from the VS Code marketplace as
**`GsonSoft-development.flua`** (its version tracks the flua release —
`release.sh` bumps `package.json` alongside the Python version, and
`--tool setup` recommends it in the generated `extensions.json`). Releases
publish it automatically: the **Publish VS Code Extension** workflow fires
on every GitHub release and publishes with an organization-scoped
marketplace PAT from the `VSCE_PAT` repo secret (global PATs retire in
January 2027; the Entra ID credential flow is the planned successor). The
extension also registers the **flua-mcp** server with Copilot on demand
(the workspace's `.vscode/mcp.json`, venv interpreter — the same entry
`docs/mcp.md` documents). Build it from source with `npm install && npm run
compile` in `vscode/`.

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
(VS Code will offer to install the **Python**, **Lua MobDebug**,
**Lua Language Server** and **Markdown Preview Mermaid** extensions — the
last one renders the diagrams in `docs/tutorial/`),
`.luarc.json` (Lua 5.4 + the HC3 globals, with the bundled **`.luals/`
type library** — LuaLS definitions for `QuickApp`, `fibaro`, `api` and
`json`, so QA code gets autocomplete and parameter hints), `AGENTS.md`
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
| `--%%type:com.fibaro.binarySwitch` | device type (defaults to binarySwitch; a type the catalog does not know falls back to its nearest hierarchy ancestor — `devices/hierarchy.json`, distilled from the HC3; only types the hierarchy never heard of are an error) |
| `--%%properties:value=false` | default device properties (plural form) |
| `--%%property:value=true` | raw property, scalar values; repeatable, merges |
| `--%%var:name=expr` | initializes a **QuickApp variable**; `expr` is a Lua expression — `'text'`, `42`, `{a=1}`, `config.color`, `os.getenv("X")` (one per line). An optional quoted string after a top-level comma is the **package value** distribution packages get: `--%%var:name=expr,"<placeholder>"` |
| `--%%clobber:name=value` | Plua-compatible spelling of the package value (replaces `--%%var:name`'s value in distribution packages) |
| `--%%uid:...` | sets `quickAppUuid` |
| `--%%description:...` | sets `userDescription` |
| `--%%model:...` | sets `model` |
| `--%%build:7` | sets `buildNumber` (a number) |
| `--%%manufacturer:...` | sets `manufacturer` |
| `--%%file:lib.lua,lib` | extra QA file, loads before main (see below) |
| `--%%speed:60` | virtual time speed (global) |
| `--%%instant:true` | instant mode (global) |
| `--%%maxhours:48` | stop after 48 virtual hours (global); timers beyond the horizon never fire and never keep the run alive — the run drains exactly at the limit |
| `--%%time:speed=2,instant=true,hours=48,start=2027/10/6 12:00:20` | combined runtime settings (global) |
| `--%%time:2027/10/6 12:00:20` | bare form: set the virtual start time |
| `--%%u:{label="lbl",text="Status"}` | one UI row (see below); repeatable, order kept |
| `--%%useUiView:true` | render the new `uiView` format instead of the legacy `viewLayout` (default false) |
| `--%%mode:offline` | pin this QA to the simulated HC3 (see below) |
| `--%%mode:online` | force this QA online against the real HC3 |
| `--%%mode:proxy` | proxy mode: mirror this QA onto the HC3 (online only, see below) |
| `--%%mode:proxy,noUI` | proxy mode, but leave the proxy's UI untouched (you edit it in the HC3's UI editor) |
| `--%%debug:refreshState=true,api=true,http=true` | debug logging: refreshStates events / `api.*` calls / `net.HTTPClient` requests (global) |
| `--%%debug:true` | shorthand for all three debug channels (`:false` disables them) |
| `--%%loglength:120` | debug line length cap (default 120) |
| `--%%warn:true` | extra runtime warnings for things the HC3 stays silent about (global) |
| `--%%trace:api,ui` | the `--trace` categories (api, ui, net, timer, `all`) as a directive (global) |
| `--%%syslog:run.json` | the `--syslog` file — one JSON line per system/trace event (global) |
| `--%%db:house.json` | seed the simulated HC3 from a JSON file (devices, rooms, scenes, globalVariables, alarms, profiles) |
| `--%%replay:house.json` | replay a recorded house session (`flua record`): seeds the sim with its devices and fires its refreshState events on the virtual timeline |
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

Seeded physical devices (no QA behind them) react to the canonical light
actions: `POST /devices/{id}/action/turnOn|turnOff|setValue` updates their
`value` like a real device (dimmers use 0/99 levels, `"on"`/`"off"`
strings work), gated by the catalog's `light` interface — sensors stay
inert. QAs and proxy devices are untouched. Giving seeded devices real QA
logic is the layer-2 design in `docs/notes/notes-device-emulation.md`.

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

### Record & replay the real house

`flua record` captures a real house session — the HC3's device snapshot
plus its refreshStates feed — into one JSON file; `--replay` plays it back
into the offline sim, so a QA is regression-tested against what actually
happened at home:

```bash
.venv/bin/flua record -o house.json --duration 60   # capture (needs HC3 credentials)
.venv/bin/flua --replay house.json qa.lua           # or --%%replay:house.json in the header
```

The recording seeds the sim with the captured devices and fires each
recorded `DevicePropertyUpdatedEvent` on the virtual timeline — QAs
subscribed with `RefreshStateSubscriber` react exactly as they would have
live, and `--speed`/`--instant` fast-forward the whole session. Recording
polls `/refreshStates` every `--interval` seconds (default 1) and stores
relative timestamps, so the replay is deterministic; events for devices the
replay run did not seed are skipped silently. The recording doubles as a
seed file: `--seed house.json` loads the devices without the events.

### `flua audit`

How much of the HC3 surface does the sim cover? One command answers:

```bash
.venv/bin/flua audit            # routes + device catalog, human-readable
.venv/bin/flua audit --json     # the same numbers for agents/CI
```

It classifies every endpoint in `docs/specs/hc3-api.json` (the distilled
swagger) as simulated or forwarded-online, and reports which catalog types
the sim gives light-like behavior to — including the gap list: types that
declare light actions but lack the `light` interface, so the sim never
emulates them. It also reports the offline type hierarchy
(`devices/hierarchy.json`, distilled from the HC3's undocumented
`/api/devices/hierarchy`): how many types it knows and how many resolve to
a cataloged ancestor — the fallback that keeps device types newer than the
catalog capture running offline. It also checks the QA templates
(`quickapp-types`): every template's `--%%type` must resolve, or
`--tool newQA`/running the QA fails — the report lists the unresolvable
ones for remapping to a parent type. The coverage floors are pinned by a
test: routes, device models, the hierarchy, and the templates can only go
up.

### Debug logging

`--%%debug:refreshState=true,api=true,http=true` turns on per-category debug
logging (any subset; it is a global directive, so an `--%%include`'d file
can carry
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
QuickApp methods. `useUiView` (default `false`) selects the new format:

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

At runtime a single select is set with `updateView(elm, "selectedItem", value)`
and a multi select with `updateView(elm, "selectedItems", {value1, value2, …})`.
Like on the HC3, an **empty** list must be `json.array()` — the marked empty
array encodes as `[]`, while a plain empty table `{}` encodes as an object
and breaks the UI. The HC3's own demos use `json.array()` for exactly this:

```lua
self:updateView("tagMulti", "selectedItems", json.array())  -- [] not {}
```

### The UI viewer

`flua --ui [PORT]` serves the viewer **itself** over HTTP, alongside the
simulated HC3 API — no file to open:

```bash
.venv/bin/flua --ui 8090 examples/ui.lua   # UI viewer on http://127.0.0.1:8090/
open http://127.0.0.1:8090/               # press Connect; the base URL matches
```

The page defaults its API address to its own origin, so a busy port falling
back to the next free one needs no editing. The page ships inside the flua
package (`src/flua/setup_templates/viewer/index.html` is the source);
`--tool setup` does not copy it — the served page can also point at another
machine running flua.

**The run timeline** lives at `http://127.0.0.1:PORT/timeline` (linked
from the viewer header): one row per QA, virtual time on the x-axis, one
mark per event from the structured feed — blue `api` calls, green `ui`
events, orange `net` operations, purple `timer` starts/expiries, gray
lifecycle. Hover a mark for its time, QA, detail, and full data. Enable the
marks with `--%%trace:api,ui,net,timer` (or `--trace all`); the page polls
`/flua/systemLog` live, so a run under `--speed`/`--instant` draws its
whole story as it happens. The buffer keeps the recent 2000 events — add
`--%%syslog:run.json` for the complete history of a run.

Per-window URL parameters (bookmarkable): `?qa=<id>` shows only that QA,
`?exclude=id[,id...]` hides those, `?bg=<color>` / `?panel=<color>` set the
page/panel colors (any CSS color), and `?view=condensed` starts in the
condensed device list (below). The **View** toggle's choice is remembered
in the browser, so your normal flow keeps the last mode. A panel's "open in
window" button opens a `?qa=` window carrying the current theme. Defaults
for the colors come from the config file's `viewer = { bg = ..., panel = ... }`
table (`.flua.lua`), served at `GET /flua/theme`.

The **View** toggle switches between the full panel view and the condensed
device list (the HC3's compact style): every device as a small status card
in wrapping rows — the value on top (sensor value + unit), the device name
in bold, the `log` property below. Handy for runs where a QA fans out many
child devices (e.g. the SolarEdge Live QA's registers); click a card to
open that device's full panel.

The viewer polls `GET /flua/devices` (the emulated devices only — in online
mode the HC3's own QAs stay out of the list), renders `properties.uiView`
(labels,
buttons, sliders, switches, single and multi selects — styled after the HC3
look), and sends interactions back through `GET /plugins/callUIEvent` — the
same contract the real HC3 UI uses, so your `onReleased`/`onChanged`/
`onToggled` methods fire exactly as on the controller. `self:updateView`
changes land live (the viewer merges `device.view` over the static
properties). The API server stays up after the QA's timers drain, so the
viewer keeps working while you tweak the file.

Two more flua-only channels round out the machine surface:

- `GET /flua/systemLog` — the structured lifecycle/crash feed (the
  machine-readable system log the real HC3 lacks): `run_start`/`run_stop`,
  `qa_load`/`qa_restart`/`qa_exit`, boot failures, callback crashes, and
  engine errors as JSON entries, with `last`/`offset` polling and
  `DELETE /flua/systemLog`.
- `GET /debugMessages` — the QA console buffer (QA lines with their tag,
  flua notices under the `flua` tag, runtime lines untagged), with the
  HC3's `filter`/`types`/`from`/`to`/`last`/`offset` query params,
  `GET /debugMessages/tags`, and `DELETE /debugMessages`.

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

### Variables in packages

A `--%%var` can declare a **package value**: a quoted string after the last
top-level comma of the expression —
`--%%var:pwd=config.secretPwd,"<set to service password>"`. Commas inside
the expression (table literals) or inside the placeholder itself are fine.
`--%%clobber:name=value` is the legacy Plua spelling of the same thing.

Which value lands in a package depends on where the package goes:

- **Distribution** (`--tool pack`, `flua export`, the `.fqa` you share or
  post on the forum): the package value, the evaluated value when no
  package value was declared. The main file's `--%%var` header lines are
  rewritten to these literals, so no expression — and no secret literal —
  travels in the file content.
- **Your own HC3** (`--tool uploadQA` as a new QA): always the real
  evaluated values — the placeholder is a distribution concern, your
  controller gets the credentials the QA needs.
- `--tool updateQA` never syncs variables: they are initializers, and the
  runtime values on your HC3 win.

Packaging evaluates the expressions the same way bootstrap does (`{config,
os}` in scope) but never loads or runs QA code — a faulty expression is a
loud packaging error naming the variable, and an expression that evaluates
to nil leaves the variable out of the package.

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

The configured location is the sim's full `/settings/location` shape
(timezone, city, units — PUT merges any scalar) and drives more than sun
times: `/panels/location`'s home panel (219) reports its lat/long,
`/weather` uses its units, and `/settings/info`'s `date`, `timestamp` and
sun fields follow the **virtual clock** — all of it served by the sim even
in online mode, so QAs reading `devices/1` see simulated time.

To set up specific controller values for a simulated run, QAs PUT the same
endpoints the HC3 accepts: `/settings/info` (any scalar field — `hcName`
also renames device 1), `/home` (scalar fields + `defaultSensors`/
`notificationClient` wholesale), and `/panels/location/{id}` (name/radius/
address/home). The virtual-clock fields (sun times, `date`, `timestamp`,
`serverStatus`) stay computed and ignore PUTs. `PUT /weather` is a flua
extension (the HC3's weather is provider-owned): it overrides any weather
field, so scene logic can react to a fixed forecast.

`os.getenv(name)` reads through flua's environment chain: the shell
environment first (so explicit per-run settings like CLI flags win), then
the local `.env` in the directory you run from, then `~/.env` as the
global fallback. Files are plain `KEY=value` lines (comments and quotes
supported) and are re-read when they change — handy for API tokens and
per-machine settings that don't belong in the QA code.

### The `--%%include` defaults directive

A QA can pull its defaults from another file — per-QA, explicit, and the
path resolves relative to the main file (like `--%%file`):

```lua
--%%include:defaults.lua      -- inserts that file's directives as defaults
--%%name:LocalName            -- this QA's own directives override them
```

```lua
-- defaults.lua — same --%% directive syntax as a QA header
--%%mode:offline              # this project normally runs offline
--%%description:local playground QA
```

The included file's directives are defaults: the QA's own win per key, the
`mode` family overrides as a whole (a QA can opt out of an included
`--%%mode:offline`), and `--%%file` lists append (defaults first, a
redeclared name wins). Includes nest — each path relative to the file
carrying the include line — and cycles are skipped; a missing include is a
loud error. This replaces the old `.directives` working-directory defaults
(the file was ambiguous when QAs lived in different subdirectories — each
QA now declares its own defaults explicitly).

### The `.flua-directives` override file

Testing someone else's QA usually needs one or two overridden values — a
password, an IP — without editing the QA (or VS Code's launch.json).
`.flua-directives`, next to the QA's **main file**, is that file: the same
`--%%` syntax as a QA header, applied as if its lines came after the QA's
own — the tester wins:

```lua
-- .flua-directives — next to main.lua; the QA's own --%%var:pwd/--%%var:host lose
--%%var:pwd=os.getenv("HC3_PASSWORD")   -- expressions work: the .env chain included
--%%var:host="192.168.1.99"
--%%mode:offline                        # or any directive, including globals
```

Discovery keys on the **directory of the path given on the CLI**: the main
file's directory, and for a `.fqa` the package's own directory (a
`.flua-directives` *inside* a package is the author's file and never
auto-applies). Every QA listed on the command line checks its own
directory, so QAs in different directories each get their own overrides; a
missing file is simply skipped. The file wins over the QA's header and its
`--%%include` defaults; explicit `-D` flags win over the file. Global
directives (`--%%time`, `--%%db`, ...) work too — they land in the run's
shared config, like `-D` does. The file often holds secrets: gitignore it,
or keep it expression-only (`os.getenv(...)`), reading values from the
`.env` chain.

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
to the main file's directory. A `$` prefix instead loads a library **bundled
with flua** (`src/flua/lua/lib/`, shipped in the wheel — plain Lua, so it
also runs on the HC3 and travels in the `.fqa` like any QA file):

```lua
--%%file:$event_mgr.lua,em   -- flua's bundled event-manager library
```

A missing bundled library (or a path-escape attempt like `$../x.lua`) is a
loud load error. See `examples/multifile.lua`. The HC3's file API works
offline too (`api.get('/quickApp/' .. _FLUA.qaId .. '/files')` etc.).

`--%%file` files are the QA's *shipped* files — they travel into the `.fqa`
(`--tool pack`, uploads). Test-only helpers (mock-server handlers, assertion
libraries) can stay out of the package: plain Lua `require("name")` finds
`name.lua` next to the main file at runtime, and require'd files are never
packaged.

## The offline HC3

### Online mode — the real HC3

The backend is picked from the **main QA's directives — `-D` flags and
`.flua-directives` over its header over any `--%%include`'d defaults**
(see below), before the engine starts:

1. an explicit `--api local|remote` always wins;
2. otherwise, `--%%mode:online`/`--%%mode:proxy` in the **main** QA's
   directives selects the real HC3, `--%%mode:offline` the offline sim;
3. otherwise, **offline** — the default: the simulated HC3, no credentials
   needed. Online is opt-in (`--%%mode:online|proxy`, or `--api remote`),
   and requires HC3 credentials in the environment (`HC3_URL`/`HC3_HOST`);
   without them flua exits with an error.

`--%%mode:offline` on a *secondary* QA pins just that QA's `api.*` calls to
the sim while the rest of the run stays online — handy for keeping test QAs
sandboxed against a live controller. The legacy `--%%offline:true` is an
alias for `--%%mode:offline`.

With `--api remote`, the `api` table talks to the real HC3: the controller
is authoritative for its resources — reads of rooms, scenes, sections,
globals, custom events, profiles, alarm partitions, panels, users and the
like come from the HC3. The sim's base structs (device 1, `/home`,
`/settings/info`, `/settings/location`) are the controller's real structs
fetched lazily on first access, with the virtual-clock fields (sun times,
date/time) computed on top. What the emulator created locally (emulated
QAs from id 5000, scene QAs) merges into those views (`/devices`,
`/plugins`, `/scenes`), and writes stay in the emulator (they do not
mutate the controller). Anything the sim doesn't know is forwarded to the
controller over HTTP — the same Lua surface, hybrid routing. Remote calls
are **asynchronous per
QA**: a slow controller call suspends only the calling QA (its timers and
events queue, like during `fibaro.sleep`) while the pump and every other
emulated QA keep running — the response resumes the QA's code exactly where
`api.get` was called. Offline (the default), calls stay synchronous — the
fast path. Credentials come from the .env chain:

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
then the main QA's directives (`--%%mode:...` — `-D` flags and
`.flua-directives` over its header over any `--%%include`'d defaults), then
the default — `offline` (the simulated HC3).

| Aspect | `offline` | `online` | `proxy` |
|---|---|---|---|
| Where the QA runs | in the emulator; device registered in the sim (id 5000+) | in the emulator; device registered in the sim (id 5000+) | in the emulator, under the proxy's HC3 id (same deviceID) |
| What exists on the HC3 | nothing | nothing | a `<name>_Proxy` QuickApp (same type and UI), deployed or reused |
| `api.*` routing | the sim only; unknown ids 404 | hybrid: resource reads from the HC3 (rooms, scenes, globals, custom events, profiles, partitions, panels, …) with emulated QAs and scene QAs merged in; unknown ids forwarded | same hybrid; the QA's own device is the proxy id |
| `self:updateProperty` / `updateView` / `setVariable` / internal storage | sim updated, event posted locally | sim updated, event posted locally | sim AND the HC3 proxy updated; the event is posted by the HC3 — never duplicated locally |
| Children (`createChildDevice` / `removeChildDevice`) | created in the sim | created in the sim | created on the HC3 as children of the proxy and shadowed in the sim under their HC3 ids (existing proxy children are shadowed at startup; removal deletes both) |
| UI interactions | the local UI viewer | the local UI viewer | the HC3 phone app, through the proxy (actions and UI events are funnelled back to the emulator); the local viewer works too |
| Reached from the HC3 (scenes, other QAs) | no | no | yes — through the proxy device |
| `refreshStates` feed | events generated by the sim | sim events + real HC3 events mirrored through the long poll | same, and the proxy's own events arrive from the HC3 |
| House entities (global variables, custom events, rooms, sections, scenes) | created/updated in the emulator | created/updated in the emulator (reads come from the HC3) | created/updated in the emulator |
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
both modes: offline, sim state changes (device creation/removal, property
updates, actions) are emitted as real-shaped `DeviceCreatedEvent` /
`DeviceRemovedEvent` / `DevicePropertyUpdatedEvent` /
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
- `self:setVariable/getVariable` — persistent, survives restarts; `--%%var`
  values are visible through `api.get('/devices/<id>').properties.quickAppVariables`
  already during `onInit` (the HC3's `initialProperties` behavior)
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

- `net.HTTPClient({timeout=ms})` → `request(url, {options, success, error})` — `examples/http.lua`
  (constructor timeout sets the per-request default; `options.timeout` overrides it.
  `options.checkCertificate = false` skips HTTPS certificate verification,
  like the HC3 — handy for self-signed certs; the default verifies)
  **SSE**: a `text/event-stream` response streams — `success` fires per raw
  event block (`{status, data, headers}`), and the stream ends **silently**
  when the server closes (the HC3's behavior); a mid-stream read timeout is
  a transport failure and reaches `error` — real services send keepalives
  just inside typical read timeouts (Hue ≈ every 58s), so treat mid-stream
  timeouts as transient: catch and reconnect, don't fail the QA. `exit()`
  cancels the QA's in-flight requests — an open stream dies with its QA.
  **Loopback API**: in online mode, requests to `127.0.0.1:11111`/`11112`
  (the HC3's loopback-only, credential-free API) are rewritten to the
  controller's standard API with the configured credentials — the same hack
  QAs on the HC3 use to avoid embedding credentials.
- `net.TCPSocket({timeout=ms})` → `connect/send/write/read/readUntil/close` — `examples/tcp.lua`
  (`write` is the HC3-documented alias of `send`)
- `net.UDPSocket({broadcast, timeout})` → `sendTo/receive` — `examples/udp.lua`
- `net.WebSocketClient()/WebSocketClientTls()` → `addEventListener`, `connect`, `send`, `sendBinary` — `examples/websocket.lua` (`connect(url, headers)` takes a headers table, like the HC3; `sendBinary` sends binary frames, and `dataReceived(payload, isBinary)` receives them — the new HC3 binary mode). Like the HC3, the TLS client does **not** verify certificates by default (embedded bridges ship self-signed certs — e.g. Dirigera); the flua extension `connect(url, headers, {checkCertificate = true})` opts back into verification.
- `mqtt.Client.connect(uri, options)` → `subscribe/publish/unsubscribe/disconnect`, `mqtt.QoS` — `examples/mqtt.lua` (`mqtts://` or `options.tls` enables TLS: `useSNI` on by default like the HC3 ≥ 5.191, `tls.useSNI = false` switches SNI off; also `allowUnauthorized`, `certificateAuthority`, `clientCertificate`)

TCP/UDP payloads are **binary-safe**: raw bytes (including NUL and values
above 0x7F) cross the bridge byte-for-byte in both directions — a payload
is escaped for the message bridge and un-escaped on the wire, so even a
literal `\x` sequence in your data round-trips intact.

### Mock servers (`net.*Server`)

A flua extension (no HC3 counterpart): a QA can **host** mock servers so its
`net.*` clients can be tested without a controller or Python. The handler
runs in the QA on every request; its return value is the reply. All servers
bind `127.0.0.1`; port 0 picks a free port (`server.port`).

```lua
local http = net.HTTPServer()
http:listen(0, function(req)               -- {method,url,headers,body}
  return {status = 200, body = "ok", headers = {["X-Mock"] = "1"}}  -- or a string, or nil (204)
end)
local tcp = net.TCPServer()
tcp:listen(0, function(data, conn) return data:upper() end)
  -- one handler call per request; return the reply, or nil for no reply.
  -- The connection stays open until the CLIENT closes it; conn is a stable
  -- per-connection id for per-client state. Payloads are binary-safe
  -- (raw bytes arrive and return byte-exact).
local udp = net.UDPServer()
udp:listen(0, function(data, ip, port) return "got:" .. data end)  -- nil = no reply
local ws = net.WebSocketServer()
ws:listen(0, function(message, isBinary) return "echo:" .. message end)
...
http:close()
```

Semantics: HTTP and WS are one-shot (request/response); TCP keeps the
connection open across requests until the client closes, UDP is one datagram
in, optional reply out. WS binary messages echo back as binary frames,
byte-safe, and TCP/UDP payloads cross the engine bridge byte-safe. A handler
that raises replies `500` (HTTP) or nothing; a handler that never returns
answers `504` after 10 s. Mock scaffolding can live in a sibling file loaded
with `require` — it runs in the QA's own environment (so it can use
`net.*Server`, `fibaro`, timers directly), and stays runtime-only, never
part of the `.fqa` package. Guard the line so the QA still runs on the real
HC3, where `require` does not exist:

```lua
if require then require("mocklib") end  -- flua only; no-op on the HC3
```

See `examples/mockServer.lua` — a QA that hosts all four and verifies its
own clients against them.

For Modbus TCP devices, `examples/Modbus Server` is a ready-made pattern:
`modbus_server.lua` serves any register table over FC3/FC6/FC16 (pick the
address base to match the QA's wire convention), `solaredge.lua` fills the
SunSpec map for a SolarEdge inverter, and `solaredge_mock.lua` wraps it in a
QA with buttons that change the values — run it next to the user QA and
press a button to watch the readings follow. See `examples/Modbus Server/README.md`.

## Deploying to the HC3

```bash
.venv/bin/flua export script.lua -o myqa.fqa
```

Upload `myqa.fqa` through the HC3 web UI (Create QuickApp → import). The
package follows the HC3's schema — only the properties the HC3 accepts
travel: the UI structures, `userDescription`, the variables, and the
identity properties a QA declares (`manufacturer`, `model`, `buildNumber`,
`deviceRole`, `quickAppUuid`). Dynamic properties are left out.

An `.fqa` file is also directly runnable — handy for testing a package you
just downloaded from the HC3 (or built with `--tool pack`):

```bash
.venv/bin/flua --api local myqa.fqa     # unpack to a temp dir and run main
.venv/bin/flua --check myqa.fqa         # static-check the packaged code
```

flua unpacks the package into a temp directory (cleaned up at exit) and
runs the generated main through the normal pipeline — name, type,
properties, UI rows, and `--%%file` extras all come back out of the
package. The QA's own `--%%` header rides along too, so a downloaded QA's
`--%%mode`/`--%%var` directives behave like they would unpacked.

Or let flua talk to the HC3 directly with the `--tool` (alias `-t`)
commands — they package/unpack for you, so you develop in the unpacked
format (individual `.lua` files) and only the HC3 sees `.fqa`:

```bash
# upload an unpacked project (main file + --%%file extras) as a new QA
.venv/bin/flua --tool uploadQA script.lua            # --room ID to place it

# update an existing QA's files from the unpacked project
.venv/bin/flua --tool updateQA 123 script.lua

# update ONE file in a downloaded QA (the VS Code task uses ${file})
.venv/bin/flua --tool uploadFile MyQA_lib_123.lua

# download a QA from the HC3 and unpack it into individual .lua files
.venv/bin/flua --tool downloadQA 123 -d project/     # -d DIR (default: QA name)

# build an offline db from the real HC3 (device 1, location, family locations)
.venv/bin/flua --tool createDB -o db.json            # -f to overwrite

# scaffold a QA project: .vscode configs + agent skills/instructions
.venv/bin/flua --tool setup [project-dir]

# scaffold a QA from a standard device type template (30 types)
.venv/bin/flua --tool newQA binarySwitch "Hall lamp"   # lists all types with no argument

# package / unpack QA projects as .fqa files (tool forms of flua export/unpack)
.venv/bin/flua --tool pack main.lua          # output: <QA name>.fqa (the --%%name), else MyQA.fqa
.venv/bin/flua --tool unpack myqa.fqa -d project/

# deploy a ready-made package as a NEW QA, or download one from the HC3
.venv/bin/flua --tool uploadFQA myqa.fqa
.venv/bin/flua --tool downloadFQA 123

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
`<QA-name>_main.lua` (from `unpack`) uploads as a new QA.

`downloadQA` also stamps every unpacked file with two metadata directives —
`--%%deviceId:123` (the HC3 device id) and `--%%qaFile:lib` (the QA file
name the file maps to). `uploadFile` reads them, so one file can be pushed
back to its QA without re-uploading the whole project — the VS Code task
"Flua: Upload file to HC3" (installed by `--tool setup`) runs it on the
file you are editing (`${file}`). Files downloaded before the directives
existed still work: the `<QA-name>_<file>_<id>.lua` file name is the
fallback. Updating the main file restarts the QA on the HC3; the tool warns
when the target QA's name no longer matches the file name (a file copied
out of another QA's project).

The HC3's export omits the identity properties (`manufacturer`, `model`,
`buildNumber`, `deviceRole`, `quickAppUuid`), so `downloadQA`/`downloadFQA`
restore them from the live device — the downloaded project/package keeps
them. They only travel in a flua package when the project declares them
(never the catalog skeleton's defaults), and `updateQA` syncs them to the
HC3 like the other standard properties.

The tools need HC3 credentials (the `.env` chain, like online mode).
`uploadQA` prints the new device id; `updateQA` puts all files at once;
`downloadQA` writes a `<QA-name>_main_<id>.lua` main with the QA's
directives plus the extra files — a normal flua project.

## Bringing an HC3 QA home

Export the QA from the HC3 UI (`.fqa`), then:

```bash
.venv/bin/flua unpack myqa.fqa -d myqa-project/
```

You get a runnable flua project: `<QA-name>_main.lua` (the QA name comes
from the package) with generated `--%%` directives and one file per QA file
— the same `<QA-name>_<file>.lua` pattern `downloadQA` uses, minus the id.
Ready for editing and debugging.

## Static checks

```bash
.venv/bin/flua --check script.lua
```

Checks syntax, unknown `--%%` directives (typos), and deprecated API calls.
Warnings don't fail the run; syntax errors exit 1. Good in CI. It checks the
**whole project**: the main file plus every `--%%file` include (a missing
include is an error, and `$name` entries resolve to flua's bundled
libraries). `--check --json` prints the findings as one JSON document
(`{"ok", "findings": [{file, severity, message}]}`) instead of prose — the
agent/CI form.

A wrong `--%%type` is an error with directions: it names close matches
(typos) and points at `flua --tool catalog`, which lists every device type
the sim supports (`--json` for a JSON array).

### Self-testing a QA (no repo needed)

A QA can be its own test suite — no pytest, no repo. Assert inside the QA,
exit with the failure count, and let the caller (a shell, CI, or a coding
agent) check the exit code:

```bash
.venv/bin/flua --api local examples/selfTest.lua   # prints PASS/FAIL lines
echo $?                                           # 0 = pass, non-zero = fail
```

Instead of hand-rolling the assertions, `require("flua-test")` — a
built-in assertions library (no files needed, nothing travels in the
.fqa):

```lua
local Test = require("flua-test")
local t = Test.new()
t:expect(cond, "msg")          -- PASS:/FAIL: line, counts failures
t:assert_eq(got, want, "msg")  -- deep compare, tables included
t:assert_json(text, "msg")     -- json.decode succeeds
t:finish()                     -- "failures: N" + exit(failures > 0 and 1 or 0)
```

Asserts can also TRAVEL to a real HC3 — declare the library as a QA file
and the same code needs no editing: on the controller every assertion
becomes a no-op (no printing, no counting, `finish()` returns 0), because
the module detects the HC3 by the absence of flua's `_FLUA` global. In
flua the shipped copy is the full library either way:

```lua
--%%file:$flua-test.lua,flua_test   -- ships in the .fqa; loads before main
local Test = require("flua-test")   -- works on the HC3 too (the file
                                    -- registers itself in package.preload)
-- ...or the shared-file idiom, no require: local t = fluaTest.new()
```

The exit code is the contract: an uncaught Lua error exits 1, and `exit(N)`
(`os.exit(N)`) exits N — the QA must end with an explicit exit, or the run
never finishes. A failing QA in a multi-QA run fails the process (the last
failing QA's code wins), and flua prints a verdict line on stderr —
`flua: QA <name> (<id>) exited with code N` — so agents can attribute the
exit code.

`flua test` runs a whole suite of self-asserting test QAs at once:

```bash
.venv/bin/flua test                       # every *_test.lua under the cwd
.venv/bin/flua test tests/                # a directory (recursive)
.venv/bin/flua test qa_test.lua           # explicit files, any name
.venv/bin/flua test --list                # show what would run
.venv/bin/flua test --timeout 10 -v       # 10s per file; verbose failures
```

Each file runs in its own flua process — a test that never exits hits the
per-file wall-clock timeout (reported as TIME, with the hint to end tests
with `t:finish()`/`exit(...)`) instead of blocking the rest. The runner
reports one PASS/FAIL/TIME line per file plus a summary and exits 0 only
when everything passes: `FAIL bad_test.lua (failures: 1)`, `1 passed,
1 failed, 0 timed out`.

### `flua doctor`

One command answers "why doesn't it work":

```bash
.venv/bin/flua doctor               # runtime, venv, HC3 credentials +
                                    # reachability, LuaLS/.vscode setup,
                                    # extension, flua-mcp, project files
.venv/bin/flua doctor --no-network  # skip the HC3 ping
.venv/bin/flua doctor --json        # machine-readable checks for agents
```

It reports one ✓/✗ line per check and exits non-zero when any check fails
— paste the block into a support question instead of describing the setup.
Secrets never appear: credentials are reported as set/unset with their
source file, never as values.

For machine-readable runs (agents parsing the log), `--log json` emits one
JSON object per line — `{time, level, tag, qaid, msg}` — with stdout kept
pure JSON and flua's own notices on stderr; `--logfile FILE` writes a copy
of the log (ANSI stripped, JSON lines with `--log json`). `--syslog FILE`
appends every structured system/crash event as one JSON line — the
complete history, where `GET /flua/systemLog` is the bounded in-memory
buffer.

`--trace LIST` adds opt-in run traces to the same channel (comma list of
`api`, `ui`, `net`, `timer`, or `all`) — one `{"event": "trace",
"data": {"category": …}}` line per: `api` — every `api.*` call a QA makes
(method, URL, status, and the request body — the arguments that usually go
wrong); `ui` — incoming device actions and `callUIEvent` interactions;
`net` — HTTP/TCP/UDP/WS/MQTT operations and results (sizes, not payloads);
`timer` — timer starts and expiries. It is the same history an agent reads
with `--syslog`, so a single file gives both the lifecycle and the QA's
behavior. Bodies are truncated at 1000 chars (they may carry secrets).
Both have `--%%` directive forms — `--%%trace:api,ui` and
`--%%syslog:run.json` — so a run's tracing can live in the QA header, an
`--%%include` file, or `.flua-directives` (the CLI flags win over them).

### MCP server (`flua-mcp`)

The same surface is available as an MCP server for hosts that prefer one
(Claude Desktop, Copilot, …). It ships with flua:

```bash
flua-mcp                  # stdio JSON-RPC (dual-era: 2026-07-28 modern, 2025-06-18 legacy)
flua-mcp --version
```

Tools: one-shot `qa_check` (static checks, `{ok, findings}`), `qa_run`
(one-shot run, `{exitCode, logs, verdict}`), `qa_ui` (structured UI
dump), and `devices` (run to completion, then the final device list from
the REST feeds) — plus the session tier for live probing: `qa_start`
keeps a running engine, `qa_probe` reads devices + new log/refreshState
lines (cursor-based deltas), `qa_action` dispatches device actions into
it, `qa_stop`/`qa_sessions` manage it. Both `qa_run` and `qa_start` take
a `trace` parameter (`api`/`ui`/`net`/`timer`, `all`): `qa_run` returns
the trace lines in its `trace` field, and a traced session feeds them
through `qa_probe`'s `systemEvents` (the same `--trace` stream).
Resources: the docs ship in the wheel and are served as
`flua://docs/*` (e.g. `flua://docs/USAGE.md`, `flua://docs/tutorial/…`) via
`resources/list`/`resources/read`, with `docs_list`/`docs_read` tools for
hosts without resource support — an agent host can read the flua docs
without a repo checkout. Prompts: `qa_debug` (seeded debugging guidance)
and `qa_skeleton` (a runnable self-testing QA template). Host
registration: add `flua-mcp` as a stdio server in your host's MCP config —
no extra install, no extra dependencies. Remote or browser hosts:
`flua-mcp --http` serves the same surface as Streamable HTTP (stateless
mode, loopback by default; `FLUA_MCP_TOKEN` is required for non-loopback
binds). The full reference (protocol surface, tool schemas, error
semantics, examples): `docs/mcp.md`.

UI behavior folds into the same loop from Lua: `_FLUA.uiEvent(element,
eventType[, value])` injects a UI event exactly as the HC3 UI would deliver
it (values arrive as strings, like the real UI), and `self:getView()`
returns the current rendered view — `updateView` changes included. A text
rendering of the UI without a browser: `flua --tool ui script.lua`; the
structured form `flua --tool ui --json script.lua` returns
`{name, type, useUiView, elements, callbacks}` — the agent form, no prose
to parse.

When the logic under test needs external interactions, serve the sim API
with `--ui PORT` and drive it over HTTP (`/plugins/callUIEvent`,
`/devices/<id>/action/<name>`, `/devices/<id>` for state), and keep timer
logic deterministic with `--start`, `--speed`, `--instant`, and `--seed`.
The `quickapp-test` skill installed by `--tool setup` documents the whole
loop for coding agents.

Every console line lands in the sim's `GET /debugMessages` buffer (the
HC3's console log, served over REST): QA lines with their tag, flua's own
notices under the `flua` tag, and runtime-level lines untagged.
`last`/`offset`/`filter`/`types` query params, `DELETE /debugMessages`
clears it, `GET /debugMessages/tags` lists the QA tags seen — a
machine-readable log feed with the same surface the real HC3 offers.

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
`net`, `mqtt`, `json`, …) — and like on the HC3 (one Lua state per QA), a
QA's `_G` **is** its own environment: `_G.x = 1` writes the QA's global
`x`, invisible to other QAs and the shared runtime. flua-specific helpers
live on `_FLUA` so your code stays portable:

- `_FLUA.qaId` — this QA's id; `_FLUA.config` — this QA's config table
- `_FLUA.mode` — this QA's effective runtime mode: `"offline"`, `"online"`
  or `"proxy"` (vs `config.mode`/`config.offline`/`config.proxy`, which are
  the directives the QA declared — a QA can pin itself offline in an online
  run)
- `_FLUA.arg` — the file path / `-e` marker
- `_FLUA.exit(code)` — stop the engine (vs `exit(code)` / `os.exit()` in a QA, which stop only that QA — `os.exit()` is the name real HC3 QAs use)
- `_FLUA.qa(id)` — another QA's QuickApp instance (lupa proxy)
- `_FLUA.loadQAfromFile(path, directives?)` / `_FLUA.loadQAfromString(code, directives?)` — dynamic QA loading; `directives` is an optional table of directive strings added to the loaded QA's config
- `_FLUA.loadFQAfromFile(path, directives?)` — like `loadQAfromFile` for a
  `.fqa` package: unpacks it to a temp dir first (the CLI's pipeline),
  name/type/UI come from the package header
- `_FLUA.async.run(fn)` / `_FLUA.async.await(worker)` / `_FLUA.async.wait(ms)` — coroutine awaits
- `_FLUA.millitime()` — virtual time in whole milliseconds (sub-second timing; `os.time()` is whole seconds, `os.clock()` is real CPU time)
- `_FLUA.postRefreshEvent(event)` — inject a fake refreshStates event
  (alarm, weather, device property change, …) to debug reactive QAs: it
  lands in the sim feed (`api.get('/refreshStates')`) and reaches every
  `RefreshStateSubscriber`; a `DevicePropertyUpdatedEvent` also updates the
  shadowed device. `created`/`sourceType` are filled in when omitted.
- `_FLUA.uiEvent(elementName, eventType[, value])` — inject a UI event
  exactly as the HC3 UI delivers it (the same route the viewer uses),
  returns `(data, status)`; the QA's callback fires async, values arrive
  as strings. The verify loop's browser-free UI testing (with
  `self:getView()` to read the rendered view).
- `_FLUA.setTimeout(fn, ms, qaId)` — timer with explicit QA attribution
- `if _FLUA then` — detect flua at runtime