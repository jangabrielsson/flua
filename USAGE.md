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
.venv/bin/flua --run-for 5 script.lua  # at least 5 s, then exit when idle
.venv/bin/flua --run-for -3 script.lua # exactly 3 s
```

Virtual time — great for testing long-running logic:

```bash
.venv/bin/flua --speed 60 script.lua    # 60x faster
.venv/bin/flua --instant script.lua     # timers fire now, os.time() jumps ahead
```

## VS Code setup

The repo ships `.vscode/launch.json` with three configurations:

- **Flua: Run Current File** — runs the file in the panel.
- **Flua: Run Current File (Terminal)** — runs it in the integrated terminal
  (pick this one for `self:debug` output you can scroll).
- **Flua: Debug Current File (mobdebug)** — real debugging: breakpoints,
  stepping, variable inspection. Install the VS Code extension
  **Lua MobDebug** (`alexeymelnichuk.lua-mobdebug`), open your QA, press F5
  with the mobdebug configuration selected. flua waits for the debugger
  before running your code.

While you step through code, `print`/`self:debug` output appears **immediately**
— logs never queue behind a paused program.

The fastest loop for tinkering:

```bash
.venv/bin/flua --watch script.lua
```

flua restarts the QA whenever you save the file (or any `--%%file` file).
Ctrl-C stops it. Works on top of the debugger too.

### Without the repo (pip install)

Installed from PyPI you don't have this checkout's `.vscode/` — drop these two
files in your project. Extensions needed: **Python** (for run/debug via
debugpy) and **Lua MobDebug** (`alexeymelnichuk.lua-mobdebug`).

`.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Flua: Run Current File",
      "type": "debugpy",
      "request": "launch",
      "module": "flua",
      "args": ["${relativeFile}"],
      "console": "internalConsole",
      "cwd": "${workspaceFolder}",
      "justMyCode": false
    },
    {
      "name": "Flua: Run Current File (Terminal)",
      "type": "debugpy",
      "request": "launch",
      "module": "flua",
      "args": ["${relativeFile}"],
      "console": "integratedTerminal",
      "cwd": "${workspaceFolder}",
      "justMyCode": false
    },
    {
      "name": "Flua: Debug Current File (mobdebug)",
      "type": "luaMobDebug",
      "request": "launch",
      "workingDirectory": "${workspaceFolder}",
      "sourceBasePath": "${workspaceFolder}",
      "listenPort": 8172,
      "stopOnEntry": false,
      "sourceEncoding": "UTF-8",
      "interpreter": "flua",
      "arguments": ["${relativeFile}"],
      "listenPublicly": true
    }
  ]
}
```

`.luarc.json` (for the **Lua Language Server** extension, `sumneko.lua`) —
the HC3 globals (`QuickApp`, `fibaro`, `api`, `net`, …) aren't type-annotated,
so the language server would flood you with undefined-global warnings:

```json
{
  "$schema": "https://raw.githubusercontent.com/LuaLS/vscode-lua/master/setting/schema.json",
  "runtime.version": "Lua 5.4",
  "workspace.ignoreDir": [".venv", "node_modules"],
  "diagnostics.disable": ["undefined-global", "lowercase-global", "undefined-field"]
}
```

If you later add HC3 type stubs, you can re-enable `undefined-global` and
point `workspace.library` at them instead.

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

Names follow plua: `--%%name:value` for scalars,
`--%%name:sub1=val1,sub2=val2` for subparameters. A typo'd directive is
silently ignored at runtime — run `flua --check` to catch those.

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

`os.getenv(name)` reads through flua's environment chain: the local `.env`
in the directory you run from, then `~/.env`, then the shell environment.
Files are plain `KEY=value` lines (comments and quotes supported) and are
re-read when they change — handy for API tokens and per-machine settings
that don't belong in the QA code.

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

The backend is picked like plua did — **peeking at the main QA file's raw
header before the engine starts** (the standard annotation parse runs
later):

1. an explicit `--api local|remote` always wins;
2. otherwise, `--%%offline:true` in the **main** QA's header selects the
   offline sim;
3. otherwise, online when HC3 credentials exist in the environment
   (`HC3_URL`/`HC3_HOST`), offline when they don't.

`--%%offline:true` on a *secondary* QA pins just that QA's `api.*` calls to
the sim while the rest of the run stays online — handy for keeping test QAs
sandboxed against a live controller.

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

`RefreshStateSubscriber` (the plua/refreshStates subscriber class) works in
both modes: offline, sim state changes (property updates, actions) are
emitted as real-shaped `DevicePropertyUpdatedEvent` /
`DeviceActionRanEvent` events — `updateProperty` only emits when the value
actually changes — and online, the poller long-polls the real HC3's
refreshStates and mirrors its events into the same feed. Both arrive at
subscribers through the message pump (plua's `_PY.newRefreshStatesEvent`
bridge hack replaced by a `refreshStateEvent` message).

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
- `GET /refreshStates?last=N` — the HC3's polling change feed

QAs find each other by name with `fibaro.getIds({type = "quickApp"})` — see
`examples/qa3.lua` and `examples/qa4.lua` calling each other.

## Loading QAs at runtime

From VS Code you often run one QA — let it bring up the QAs it needs:

```lua
local id = _FLUA.loadQAfromFile("examples/qa3.lua")   -- annotations parsed
local id2 = _FLUA.loadQAfromString([[ ...inline QA... ]])
fibaro.call(id, "turnOn")   -- immediately reachable
```

Both return the new QA id (or `nil, error`). `examples/dynamic.lua` demos it.

## Network clients

Real network, HC3-style APIs, all asynchronous through the pump (callbacks
run in your QA, timers keep running while requests are in flight):

- `net.HTTPClient()` → `request(url, {options, success, error})` — `examples/http.lua`
- `net.TCPSocket({timeout=ms})` → `connect/send/read/readUntil/close` — `examples/tcp.lua`
- `net.UDPSocket({broadcast, timeout})` → `sendTo/receive` — `examples/udp.lua`
- `net.WebSocketClient()/WebSocketClientTls()` → `addEventListener`, `connect`, `send` — `examples/websocket.lua`
- `mqtt.Client.connect(uri, options)` → `subscribe/publish/unsubscribe/disconnect`, `mqtt.QoS` — `examples/mqtt.lua`

## Deploying to the HC3

```bash
.venv/bin/flua export script.lua -o myqa.fqa
```

Upload `myqa.fqa` through the HC3 web UI (Create QuickApp → import). The
package follows the HC3's schema — only the properties the HC3 accepts
travel; dynamic properties are left out.

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

## flua extensions (`_FLUA`)

Everything HC3-compatible is a plain global (`QuickApp`, `fibaro`, `api`,
`net`, `mqtt`, `json`, …). flua-specific helpers live on `_FLUA` so your code
stays portable:

- `_FLUA.qaId` — this QA's id; `_FLUA.config` — this QA's config table
- `_FLUA.arg` — the file path / `-e` marker
- `_FLUA.exit(code)` — stop the engine (vs `exit(code)` which stops only this QA)
- `_FLUA.qa(id)` — another QA's QuickApp instance (lupa proxy)
- `_FLUA.loadQAfromFile(path)` / `_FLUA.loadQAfromString(code)` — dynamic QA loading
- `_FLUA.async.run(fn)` / `_FLUA.async.await(worker)` / `_FLUA.async.wait(ms)` — coroutine awaits
- `_FLUA.millitime()` — virtual time in whole milliseconds (sub-second timing; `os.time()` is whole seconds, `os.clock()` is real CPU time)
- `_FLUA.setTimeout(fn, ms, qaId)` — timer with explicit QA attribution
- `if _FLUA then` — detect flua at runtime