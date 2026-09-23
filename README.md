# flua

A Lua engine for Fibaro QuickApps: [lupa](https://github.com/scoder/lupa) (bundled
Lua 5.x) hosted in Python, asyncio-backed cooperative timers on a virtual clock,
and a strict message-passing bridge between the two sides. On top of that
skeleton flua runs **real QuickApps offline** — a simulated HC3 REST API, the
HC3 runtime libraries, and the full HC3 network surface (HTTP, TCP, UDP,
WebSocket, MQTT) — all with `lupa` as the only runtime dependency.

A smaller, more targeted rewrite of [plua](https://github.com/jangabrielsson/plua)
with the architecture lessons from it baked in.

**QA developers start at [USAGE.md](USAGE.md)** — install, VS Code setup,
directives, multi-file QAs, the offline HC3, and deploying to the HC3.
The rest of this file is how flua works under the hood.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Requires Python 3.11+. `lupa` is the only runtime dependency.

## Usage

```bash
# run one or more QuickApp files (each isolated)
.venv/bin/flua examples/timers.lua
.venv/bin/flua examples/qa3.lua examples/qa4.lua

# one-liner
.venv/bin/flua -e 'setTimeout(function() print("hi") end, 100)'

# lifetime control (--run-for counts VIRTUAL seconds — under --speed/--instant
# it measures simulated time; at realtime speed virtual seconds == wall seconds)
.venv/bin/flua --run-for 0 script.lua    # run until exit()
.venv/bin/flua --run-for 5 script.lua    # at least 5 virtual s, then exit when idle
.venv/bin/flua --run-for -3 script.lua   # exactly 3 virtual s

# ANSI colors on QA log lines (debug=green, trace=cyan, warning=orange,
# error=red — plua style): always (default), auto, never
.venv/bin/flua --color always script.lua

# simulated HC3 (offline): seed the REST API with a house
.venv/bin/flua --seed examples/house.json script.lua

# UI viewer: serve the sim API for viewer/index.html (stays up until Ctrl-C,
# busy ports fall back to the next free one)
.venv/bin/flua --ui 8090 examples/ui.lua

# develop: watch mode (restart on save), static checks, deploy artifacts
.venv/bin/flua --watch script.lua
.venv/bin/flua --check script.lua
.venv/bin/flua export script.lua -o script.fqa
.venv/bin/flua unpack script.fqa -d project/

# virtual time: accelerated or instant simulation
.venv/bin/flua --speed 60 script.lua     # 60x faster
.venv/bin/flua --instant script.lua      # timers fire now, time jumps ahead

# remote debugging (mobdebug; VS Code Lua extension or ZeroBrane)
.venv/bin/flua --debugger script.lua     # port 8172 (default)
```

With no `--run-for`, flua exits gracefully when no timers, messages, or open
network connections are pending — a script with no timers just runs and exits,
like the standard interpreter (`--ui` is the exception: it keeps the run alive
until Ctrl-C so the viewer never loses its API). On startup flua prints a
greeting with the flua, Lua and Python versions (`--nogreet` to skip it).

Each file is started as a tracked `setTimeout` callback with delay 0, so it
runs inside the engine's message pump.

## QuickApps

Every Lua file is a QuickApp, like on the HC3 — it gets the real `QuickApp`/
`QuickAppBase` classes, `fibaro`, the `api` table and the network modules:

- **Isolated globals.** Each QA runs in its own environment in the same Lua
  state: global writes land in a per-QA table, reads fall through to the
  shared runtime globals (`setTimeout`, `print`, `async`, `os`, ...). Two
  QAs can define a global `x` without clashing.
- **Per-QA timers.** Each QA gets its own `setTimeout`/`clearTimeout`/
  `setInterval`/`clearInterval` wrappers that delegate to the runtime
  timers with QA attribution — the engine tracks which timers belong to
  which QA (`engine.qa_timer_count(id)`, one source of truth). `exit(code)`
  terminates the calling QA (HC3 semantics: it cancels that QA's timers and
  the others keep running); `_FLUA.exit(code)` stops the engine.
- **Bootstrap.** The engine assigns the QA id (unique, starting at 5000 —
  like the HC3, user code cannot pick its own id), builds the device from
  the config, and constructs the QuickApp instance — `QuickApp:onInit` runs
  inside the QA's tracked timer, so timers scheduled by `onInit` belong to
  that QA. `--%%type` selects the device type; the instance is built from
  the **device type skeleton** (`src/flua/devices/devices.json` — 176 real
  HC3 captures, scrubbed of instance data), with `--%%properties` overlaying
  defaults. The instance is exposed as `_FLUA.qa(qaId)`.
- **Device types.** `--%%type` selects the skeleton; omitting it defaults to
  `com.fibaro.binarySwitch`, and an unknown type is an error at startup.
- **Config.** The CLI builds the config for each QA (CLI flags + global
  `--%%` annotations plus the QA's local `--%%` annotations) and exposes it
  on that QA's own `_FLUA.config` — so `--%%name:qa1` appears as
  `_FLUA.config.name` for that QA only, stable even in deferred reads.
  Directives form a header; parsing stops at the end-of-header comment
  `-- --------------- EOH ---------------` (plua convention), so `--%%`
  lines later in the file (e.g. inside inline QA code) are ignored.
- **Dynamic loading.** A QA can install and run another QA at runtime —
  handy from VS Code, where you only launch one QA:
  `_FLUA.loadQAfromFile(path)` (the file's `--%%` annotations are parsed)
  and `_FLUA.loadQAfromString(code)` (written to a temp file first, then
  the same file pipeline). Both return the new QA id, or `(nil, error)`,
  and the new QA is immediately reachable through `fibaro.call` — see
  `examples/dynamic.lua`.
- **Multi-file QAs.** `--%%file:path,name` directives declare extra files
  that load into the QA in declaration order before the main file (paths
  resolve relative to the main file's directory) — see
  `examples/multifile.lua`. On the HC3 files have no paths, only names:
  the main file is named `main` and extras use their directive names.
- **QA file management.** The HC3's `/api/quickApp/*` routes work offline:
  `GET /quickApp/{id}/files`, `GET|PUT|DELETE /quickApp/{id}/files/{name}`
  (changes restart the QA — the main file is read-only offline, it lives on
  your disk), `GET /quickApp/export/{id}` exports a `.fqa` package and
  `POST /quickApp/import` installs one (the documented base64 body or a
  direct table). The encrypted `.fqax` export is not supported (501) — it is
  Fibaro-specific.
- **Directory.** The engine keeps a Python-side QA directory:
  `engine.qa_ids()`, `engine.qa_info(id)` (name, path, files, loaded flag)
  and `engine.qa_instance(id)` (the QuickApp as a lupa proxy). It is filled
  at start and updated via the `qaLoaded` message when the QA finishes
  loading.
- **_FLUA vs _PY.** Each QA's environment has its own `_FLUA`: `qaId`,
  `config` and `arg` are that QA's own values; everything else (timers,
  `async`, `json`, `qa(...)`, dynamic loading, ...) delegates to the shared
  engine table. QA code can detect flua with `if _FLUA then ... end`. The
  bare globals (`setTimeout`, `print`, `QuickApp`, `fibaro`, `json`, `api`,
  `net`, `mqtt`, ...) are the HC3 environment. `_PY` is the pure Python
  bridge — user code should not touch it.

## Simulated HC3 REST API (offline)

The `api` table (`api.get/post/put/delete(path, body)`) is the real HC3 REST
surface, served by a simulated HC3 built from the running QAs plus `--seed`
state. Unknown paths return `(nil, 404)` like the HC3. Implemented:

- **devices** — list/query (`type`, `parentId`, `interface`, `visible`,
  `enabled`, `roomID`), get/update/delete, `/properties/{name}`
- **plugins** — variables CRUD with the HC3 status contract, `createChildDevice`,
  `updateProperty`, `updateView`, `interfaces`, `restart`
- **actions** — `POST /devices/{id}/action/{name}` and `groupAction` run
  `QuickApp` methods via the pump (`fibaro.call` between QAs works offline);
  `customEvents` fire `onCustomEvent` handlers
- **scenes / alarms / profiles** — metadata + run state, arm/disarm,
  active-profile switching
- **globalVariables / rooms** — seeded + mutable
- **refreshStates** — `GET /refreshStates?last=N` change/event feed for
  polling QAs (the HC3's documented shape)

Seed a house with `--seed house.json` (devices, rooms, scenes,
globalVariables, alarms, profiles). See `.github/skills/hc3-rest-api/` for the
endpoint reference the sim mirrors.

## UI viewer

`viewer/index.html` is a standalone page that renders QuickApp UIs and injects
interactions through the sim API — the same contract the real HC3 UI uses.
Serve the channel and open the file in a browser:

```bash
.venv/bin/flua --ui 8090 examples/ui.lua   # then open viewer/index.html
```

- polls `GET /devices` every second and renders `properties.uiView` (live
  state merged from `device.view` — `QuickApp:updateView` shows up without a
  reload)
- clicks, slides and toggles fire `GET /plugins/callUIEvent`, which delivers
  the event through the QA's own `UIAction` exactly like a tap in the real UI
- a busy port falls back to the next free one, so parallel runs and quick
  restarts never collide — the effective port is printed at startup
- permissive CORS, so the page works straight from `file://`
- with no `--run-for` the run stays up until Ctrl-C; an explicit `--run-for`
  still bounds the session
- the same page works against a real HC3: point it at the gateway's address
  and fill in credentials

## Network clients

All five network modules follow the same pattern: operations run in **Python
worker threads** (never blocking the pump), results come back through the pump
as messages, and callbacks run in the QA's own environment. Everything is
stdlib (urllib, sockets, ssl, RFC 6455 / MQTT 3.1.1 framing) — `lupa` stays the
only dependency. Open connections count as pending work, so the process stays
alive until they close.

- **`net.HTTPClient`** — async HTTP; any completed exchange (even 4xx/5xx)
  reaches `success`, transport failures reach `error`. `examples/http.lua`.
- **`net.TCPSocket`** — the HC3's callback API: `connect`/`send`/`read`/
  `readUntil`/`close`, options `{timeout = ms}`. `examples/tcp.lua`.
- **`net.UDPSocket`** — `sendTo`/`receive` datagrams, `{broadcast, timeout}`.
  `examples/udp.lua`.
- **`net.WebSocketClient` / `net.WebSocketClientTls`** — ws/wss clients,
  event-driven via `addEventListener("connected"|"disconnected"|"error"|
  "dataReceived")`. `examples/websocket.lua`.
- **`mqtt.*`** — MQTT 3.1.1 client with the HC3's documented API:
  `mqtt.Client.connect(uri, options)` (TLS, auth, lastWill, keep-alive),
  `mqtt.QoS`, `subscribe`/`unsubscribe`/`publish`/`disconnect` returning
  packet ids, and the full event set (`connected`, `subscribed`,
  `unsubscribed`, `message`, `published`, `closed`, `error`).
  `examples/mqtt.lua`.

## Timer API (Lua side)

- `setTimeout(fn, ms) -> id` — run `fn` once after `ms` milliseconds
- `clearTimeout(id)` — cancel a pending timeout
- `setInterval(fn, ms) -> id` — run `fn` every `ms` milliseconds (built on
  setTimeout chaining, so it is cooperative — a callback that runs long delays
  the next tick)
- `clearInterval(id)` — stop an interval
- `print(...)` — immediate, colorized, HC3-styled output (never queued)

Errors inside timer callbacks are caught, printed with a traceback, and the
engine keeps running.

Note on timer handles: a local is only in scope from the statement after its
declaration, so a callback that references its own handle must use the
two-step form:

```lua
local iv
iv = setInterval(function() clearInterval(iv) end, 1000)
-- not: local iv = setInterval(function() clearInterval(iv) end, 1000)
```

### Async / await (Lua coroutines)

`_FLUA.async.run(fn, onError?)` runs a coroutine that can await asynchronous
results without blocking the pump (flua-specific, hence on `_FLUA`):

```lua
_FLUA.async.run(function()
  local v = _FLUA.async.await(function(finish)
    setTimeout(function() finish(42) end, 50)
  end)
  print(v)  -- 42, after the timer fires
end)
```

- `async.await(worker)` — suspends the coroutine and calls `worker(finish)`.
  When the async work completes it calls `finish(...)` and the coroutine
  resumes; `await` returns whatever `finish` was called with.
- `async.wait(ms)` — await over a plain setTimeout.
- Errors in the coroutine go to `onError` (default: printed with a traceback,
  engine keeps running)

## Message protocol

Because lupa has reentrancy issues, the bridge is **message passing**.
Every message is a plain JSON-compatible dict (strings, numbers, booleans,
`nil`, arrays, objects) with a mandatory string `type` field. Functions never
cross the boundary — callbacks are addressed by integer IDs registered on the
Lua side. Strings crossing the bridge must be valid UTF-8: a sanitizer
hex-escapes invalid bytes instead of letting lupa's strict decoder crash the
process (printing a binary pattern like `utf8.charpattern` is safe). The
format is deliberately transport-agnostic: if flua ever grows threads,
subprocesses, or sockets, the same messages serialize with zero changes.

The full type list lives in `src/flua/messages.py` — timers, QA lifecycle
(start/restart), the API (`deviceAction`, `customEvent`), and the network
ops (`httpRequest`/`httpResult`, `tcp*`, `udp*`, `ws*`, `mqtt*`). Adding a
new type:

1. Python: add a handler to `LuaEngine._handlers` in `engine.py`.
2. Lua: add `handlers.myType = function(msg) ... end` in `lua/init.lua`.
3. Responses flow back through `engine.enqueue_outbound(...)`.

## Architecture

**Full detail, with diagrams, lives in [ARCHITECTURE.md](ARCHITECTURE.md)** —
the single-entry discipline, message flow, the dispatcher's hybrid routing,
worker threads, virtual time, online mode, and the invariants. This section
is the short version.

```
Lua code  -> _PY.post(msg)          -> inbound deque
pump      -> handler(msg)           -> timers, api state, worker tasks
workers   -> enqueue_outbound(msg)  -> outbound asyncio.Queue
pump      -> _PY.dispatch(batch)    -> Lua handles results (timer fires, callbacks)
```

One asyncio loop, one thread. The pump task is the **only** place that enters
the Lua VM (`_PY.dispatch`), and it never does so while Lua is on the stack:
Lua→Python traffic is append-only, and Python handlers never call Lua
directly — they enqueue outbound messages. This eliminates lupa reentrancy
hazards by construction.

Blocking I/O (HTTP, TCP, UDP, WebSocket, MQTT) runs in worker threads; results
hop back onto the loop thread-safely (`call_soon_threadsafe`) and ride the
pump. The only deliberately blocking main-thread calls are the debugger's
sockets — that is what makes debugger pauses freeze time.

Everything else is cooperative: timer callbacks run on the event loop, so a
long-running callback delays everything else, exactly like plua and like the
Fibaro QuickApp model.

## Files

```
src/flua/engine.py      LuaEngine: lupa VM, queues, handler registry, pump
src/flua/api/           simulated HC3 REST API: router, state, route handlers
src/flua/timers.py      TimerManager: virtual-clock setTimeout
src/flua/messages.py    message type constants + builders
src/flua/config.py      --%% annotation parsing + global/local split
src/flua/bindings.py    the _PY table (post, api, log, net/mqtt entry points)
src/flua/clock.py       VirtualClock (speed / instant / debugger freeze)
src/flua/http.py        urllib-based blocking HTTP (worker threads)
src/flua/websocket.py   RFC 6455 client over stdlib sockets + ssl
src/flua/mqtt.py        MQTT 3.1.1 client over stdlib sockets + ssl
src/flua/sync_socket.py blocking LuaSocket-compatible TCP/UDP pools
src/flua/devices/       device type skeletons (devices.json catalog)
src/flua/lua/init.lua   Lua runtime: registry, timers, dispatch, bootstrap
src/flua/lua/quickapp.lua  QuickApp/QuickAppBase/QuickAppChild classes
src/flua/lua/fibaro.lua    the fibaro API (HC3-compatible)
src/flua/lua/net.lua       HTTPClient, TCPSocket, UDPSocket, WebSocketClient
src/flua/lua/mqtt.lua      mqtt.* client wrapper
src/flua/lua/json.lua      HC3-compatible json
src/flua/lua/socket.lua    LuaSocket-compatible subset (mobdebug)
src/flua/lua/mobdebug.lua  vendored remote debugger (Paul Kulchenko, MIT)
src/flua/cli.py         CLI: bootstrap, --run-for, --seed, --debugger, ...
```

## Testing

```bash
.venv/bin/pytest                    # everything (158 tests)
.venv/bin/pytest tests/test_api.py  # the offline HC3 REST API
.venv/bin/pytest tests/test_http.py # network clients
```

Layers: pure-Python unit tests (timers, clock, config, the API router),
engine tests through a real lupa VM (message round-trips, QA lifecycle,
multi-file QAs, network round-trips against local echo servers / a minimal
MQTT broker / an RFC 6455 server), and CLI-level tests that run the actual
`flua` binary end to end. `tests/lua/*.lua` are end-to-end Lua scripts run
through the CLI by `tests/test_lua.py` (the shared harness is
`tests/lua/helpers.lua`; every `test_*.lua` there is discovered
automatically).

## Virtual time

Timers run on the engine's virtual clock, and `os.time()` (integer seconds)
and `os.date()` (and `_PY.now()`) read that clock; `os.clock()` stays Lua's
real runtime clock. Modes, via CLI flags:

- `--speed 1` (default) — realtime; virtual time tracks the wall clock
- `--speed N` — virtual time runs N times faster; timers fire at the correct
  virtual deadline, so absolute-time math stays consistent
- `--instant` — timers fire immediately and virtual time jumps to each
  timer's deadline: a script that waits for days of simulated time completes
  in milliseconds with `os.time()` showing the corresponding future time
- `--start "2027/10/6 12:00:20"` (or `--%%time:start=...` / the bare
  `--%%time:<when>` form) — set the virtual clock's starting time, so a QA
  can be run at New Year, a leap day, or any interesting date

Because the clock is virtual, the debugger pause freezes it too (see
Debugging below): a timer scheduled as `setTimeout(fn, 1000*(t - os.time()))`
fires when virtual time reaches `t`, exactly as the code anticipated.

## Config annotations

Scripts can carry config headers as ordinary Lua comments, parsed by Python
before the engine starts:

```lua
--%%speed:2
--%%instant:true
--%%time:speed=2,instant=true,hours=48
--%%name:my-qa
--%%type:com.fibaro.remoteColorController
--%%properties:value=false
--%%var:apiKey=secret
--%%uid:qa-uuid
--%%description:my QA
--%%model:model-x
--%%build:3
--%%manufacturer:fibaro
--%%property:value=true
--%%file:lib.lua,lib
```

Format: `--%%name:value` (scalar) or
`--%%name:sub1=val1,sub2=val2,...` (subparameters). Values may be booleans,
numbers, `nil`, quoted or bare strings. Repeated `--%%file:` directives
collect in declaration order.

`--%%var:name=value` initializes a **QuickApp variable** (readable with
`self:getVariable(name)`); values are literal strings, repeated directives
merge, and several variables may share one line.

Named property directives map directly onto device properties:
`--%%uid` (quickAppUuid), `--%%description` (userDescription), `--%%model`
(model), `--%%build` (buildNumber, a number), `--%%manufacturer`
(manufacturer). The raw form `--%%property:name=value` sets any property
directly (values parse as scalars — `--%%property:value=true` initializes
the value property); repeated directives merge. The plural
`--%%properties:` form still works the same way.

Parameters are either **global** or **local**:

`--%%var:name=expr` initializes a QuickApp variable, where `expr` is a Lua
expression evaluated at bootstrap with `{config, os}` in scope — so values
can be Lua data (`{a=1}`, `42`, `'text'`) or come from the Lua config file
(`.flua.lua`, local or `~/.flua.lua`, legacy `~/.plua/config.lua` — a chunk
that `return`s a table, merged into `_FLUA.config`) or the .env chain
(`os.getenv("X")`). Initializers only set missing variables, so runtime
changes persist across restarts.

- **Local** (everything not listed below) stay on the QA's own `config` —
  e.g. `--%%name:qa1` gives that QA `config.name`.
- **Global** (`speed`, `instant`, `maxhours`, `time`) are copied up to the
  shared config and apply engine-wide; the **last file that sets one wins**.
  They are also visible on every QA's `config`.

The global config is exposed to Lua as `_FLUA.config`. CLI flags override
annotations.

## Debugging (mobdebug)

flua bundles [MobDebug](https://github.com/pkulchenko/MobDebug) (v0.801, MIT,
vendored unmodified) so VS Code (Lua/mobdebug extension) or ZeroBrane Studio
can debug flua scripts remotely:

```bash
.venv/bin/flua --debugger script.lua       # port 8172 (default)
.venv/bin/flua --debugger 8173 script.lua  # custom port
```

In VS Code, use the **Flua: Debug Current File (mobdebug)** launch config
(requires the Lua MobDebug extension, `alexeymelnichuk.lua-mobdebug`). flua
accepts `-l` (ignored, Lua CLI compatibility), runs `-e` code before the
script like the Lua CLI, and resolves `vscode-mobdebug` to its own mobdebug.
`MOBDEBUG_PORT` in the environment is honored like the `--debugger` flag.

- The debugger attaches before the script runs; script files are loaded via
  `loadfile` with their real path, so breakpoints match file locations
- If no IDE is listening, mobdebug prints a connect error and the script
  runs normally
- **Logs print immediately while stepping** — QA log lines go straight to
  stdout (they never ride the queue), so `self:debug(...)` shows up as you
  step over it
- **Stopped time.** mobdebug pauses the program by blocking in a socket
  receive. Because flua's socket layer is synchronous, a pause blocks the
  main thread and freezes the asyncio loop — no timer callbacks fire while
  paused — and the virtual clock stands still: the freeze is noted just
  before the debugger's blocking receive, and the next pump tick advances
  time only up to the freeze point. Absolute-time math stays consistent —
  a timer due in 10 virtual seconds still fires 10 virtual seconds after
  the pause, not "10 seconds minus however long you stared at the
  debugger".

### LuaSocket subset

mobdebug needs synchronous sockets, provided by `require("socket")` — a
LuaSocket-compatible subset over plain Python blocking sockets
(`src/flua/sync_socket.py`): `socket.tcp()` (`connect`, `settimeout`,
`send`, `receive`, `close`, `getsockname`), `socket.bind` +
`server:accept()`, and LuaSocket return conventions
(`nil, "timeout", partial` / `nil, "closed", partial`). Not implemented:
`socket.sleep`, UDP, HTTP, `select`.

These calls run on the main thread and may block the asyncio loop — that is
the one deliberate exception to flua's message-passing model, and it is what
makes debugger pauses freeze time. All other I/O stays on the message model.

## Differences from plua

- No FastAPI subprocess and no telnet/REPL — the offline HC3 API is served
  by the same in-process dispatch the QAs use (an external HTTP server can
  be added later as a second transport over the same layer).
- No third-party network dependencies — plua used aiohttp/aiomqtt; flua
  implements HTTP (urllib), RFC 6455 WebSockets, and MQTT 3.1.1 over
  stdlib sockets in worker threads.
- plua calls `_PY.timerExpired(id)` directly from timer callbacks; flua
  delivers a `timerExpired` message through the pump instead. The call shape
  is identical but the entry is single and the protocol is serializable.
- Timer IDs are Lua callback IDs (integers), not UUIDs.
- Keep-alive is computed entirely on the Python side
  (`engine.has_pending_work()`), not by Lua-side counters.