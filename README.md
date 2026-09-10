# flua

A minimal Lua engine: [lupa](https://github.com/scoder/lupa) (bundled Lua 5.x)
hosted in Python, asyncio-backed cooperative timers, and a strict
message-passing bridge between the two sides. A smaller, more targeted
version of [plua](https://github.com/jangabrielsson/plua) — no FastAPI, no
Fibaro emulation, no networking. Just the runtime skeleton those systems are
built on.

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
.venv/bin/flua examples/qa1.lua examples/qa2.lua

# one-liner
.venv/bin/flua -e 'setTimeout(function() print("hi") end, 100)'

# lifetime control
.venv/bin/flua --run-for 0 script.lua    # run until exit()
.venv/bin/flua --run-for 5 script.lua    # at least 5 s, then exit when idle
.venv/bin/flua --run-for -3 script.lua   # exactly 3 s

# ANSI colors on QA log lines (debug=green, trace=cyan, warning=orange,
# error=red — plua style): always (default), auto, never
.venv/bin/flua --color always script.lua
```

With no `--run-for`, flua exits gracefully when no timers or messages are
pending — a script with no timers just runs and exits, like the standard
interpreter. On startup flua prints a greeting with the flua, Lua and Python
versions (`--nogreet` to skip it).

Each file is started as a tracked `setTimeout` callback with delay 0, so it
runs inside the engine's message pump.

## QuickApps

Every Lua file is a QuickApp. There is no QuickApp class yet — a QA is
simply a file with its own environment:

- **Isolated globals.** Each QA runs in its own environment in the same Lua
  state: global writes land in a per-QA table, reads fall through to the
  shared runtime globals (`setTimeout`, `print`, `async`, `os`, ...). Two
  QAs can define a global `x` without clashing.
- **Per-QA timers.** Each QA gets its own `setTimeout`/`clearTimeout`/
  `setInterval`/`clearInterval` wrappers that delegate to the runtime
  timers with QA attribution in the `setTimeout` message — the engine
  tracks which timers belong to which QA (`engine.qa_timer_count(id)`,
  one source of truth). Fired timers untrack themselves.
- **Config.** The CLI builds a global config (CLI flags + global `--%%`
  annotations) and copies it into each QA as `config`, merged with the QA's
  local `--%%` annotations — so `--%%name:qa1` appears as `config.name`.
  When a QA loads, its config is also merged into the shared `_FLUA.config`
  table (the last loaded QA wins there), so `_FLUA.config.name` works too.
  `config` stays the stable per-QA copy for deferred reads.
- **Runtime libraries.** Before the QA code runs, `quickapp.lua` and
  `fibaro.lua` are loaded into the QA's environment (in that order), so
  `QuickApp`, `QuickAppBase`, `fibaro`, `plugin`, `hub` and friends are
  available — each QA gets its own copies (quickapp.lua defines its own
  `class` per QA). The HC3-style
  `__fibaro_add_debug_message` global (a Lua global on the real HC3, used by
  `fibaro.debug/trace/warning/error`) and an `api` stub (HC3 REST, returns
  empty data with a warning until the real client lands) keep prints and
  QuickApp construction working.
- **Bootstrap.** After the QA code has loaded, the engine constructs the
  QA's QuickApp instance from its config and registers it as
  `_FLUA.qa(qaId)` (Lua side). IDs are always assigned by the engine —
  unique, starting at 5000 and incrementing per QA (like the real HC3,
  user code cannot pick its own id). Names are not required to be unique —
  defaulting to `--%%name`, then the filename (without path/suffix).
  `--%%type` and `--%%properties` feed the device table. Construction runs
  `QuickApp:onInit` — like the HC3 at startup — inside the QA's tracked
  timer, so timers scheduled by `onInit` belong to that QA.
- **Directory.** The engine keeps a Python-side QA directory:
  `engine.qa_ids()`, `engine.qa_info(id)` (name, path/code, loaded flag)
  and `engine.qa_instance(id)` (the QuickApp as a lupa proxy). It is
  filled at start and updated via the `qaLoaded` message when the QA
  finishes loading. The old plua-style `registerQAGlobally` callback is
  gone — the bootstrap registers the instance directly.
- **_FLUA vs _PY.** The engine's Lua-side API (timers, `async`, `exit`, QA
  support, `config`) lives in the `_FLUA` table; the bare globals
  (`setTimeout`, `async`, ...) are aliases for it. `_PY` is the pure Python
  bridge (`post`, `now`, `vtime`, `tcp_*`, ...) — user code should not touch
  it.

## Timer API (Lua side)

- `setTimeout(fn, ms) -> id` — run `fn` once after `ms` milliseconds
- `clearTimeout(id)` — cancel a pending timeout
- `setInterval(fn, ms) -> id` — run `fn` every `ms` milliseconds (built on
  setTimeout chaining, so it is cooperative — a callback that runs long delays
  the next tick)
- `clearInterval(id)` — stop an interval
- `exit(code)` — stop the engine with the given exit code
- `print(...)` — routed through the message queue to stdout
- `_PY.now()` — engine time in seconds (the virtual clock — direct, pure)

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

`async.run(fn, onError?)` runs a coroutine that can await asynchronous results
without blocking the pump:

```lua
async.run(function()
  local v = async.await(function(finish)
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

Cooperative by construction: suspension is setTimeout messages, so the pump
keeps running while any number of coroutines wait.

## Message protocol

Because lupa has reentrancy issues, the bridge is **message passing**.
Every message is a plain JSON-compatible dict (strings, numbers, booleans,
`nil`, arrays, objects) with a mandatory string `type` field. Functions never
cross the boundary — callbacks are addressed by integer IDs registered on the
Lua side. The format is deliberately transport-agnostic: if flua ever grows
threads, subprocesses, or sockets, the same messages serialize with zero
changes.

### Lua → Python (posted via `_PY.post`)

| type | payload | effect |
|---|---|---|
| `setTimeout` | `{id: int, delay: int}` | schedule a timer (ms) |
| `clearTimeout` | `{id: int}` | cancel a timer |
| `log` | `{level: str, text: str}` | write to stdout |
| `exit` | `{code: int}` | stop the engine |

### Python → Lua (delivered in batches via `_PY.dispatch(batch)`)

| type | payload | effect |
|---|---|---|
| `timerExpired` | `{id: int}` | run the registered callback once |

Pure synchronous helpers (`_PY.now()`, `_PY.version()`) are direct calls —
they never touch Lua state, so they are safe at any depth.

### Adding a new message type

1. Python: add a handler to `LuaEngine._handlers` in `engine.py`
   (`messages.MY_TYPE: self._handle_my_type`). Handlers may be coroutines —
   that is the seam where future asyncio work (HTTP, MQTT) plugs in.
2. Lua: add `handlers.myType = function(msg) ... end` in `lua/init.lua`.
3. Responses flow back through `engine.enqueue_outbound(...)`.

## Architecture

```
Lua code  -> _PY.post(msg)          -> inbound deque
pump      -> handler(msg)           -> side effects (timers, future I/O)
handlers  -> enqueue_outbound(msg)  -> outbound asyncio.Queue
pump      -> _PY.dispatch(batch)    -> Lua handles results (timer fires)
```

One asyncio loop, one thread. The pump task is the **only** place that enters
the Lua VM (`_PY.dispatch`), and it never does so while Lua is on the stack:
Lua→Python traffic is append-only (`_PY.post` plus pure helpers), and Python
handlers/timers never call Lua directly — they enqueue outbound messages.
This eliminates lupa reentrancy hazards by construction.

Everything is cooperative: timer callbacks run on the event loop, so a
long-running callback delays everything else, exactly like plua and like the
Fibaro QuickApp model.

## Files

```
src/flua/engine.py    LuaEngine: lupa VM, queues, handler registry, pump
src/flua/timers.py    TimerManager: asyncio setTimeout
src/flua/messages.py  message type constants + builders
src/flua/config.py   --%% annotation parsing + global/local split
src/flua/bindings.py  the _PY table (post + pure helpers + tcp_*)
src/flua/sync_socket.py blocking LuaSocket-compatible TCP (mobdebug)
src/flua/lua/init.lua Lua runtime: registry, timers, async/await, print, dispatch
src/flua/lua/socket.lua LuaSocket-compatible subset over sync_socket.py
src/flua/lua/mobdebug.lua vendored remote debugger (Paul Kulchenko, MIT)
src/flua/cli.py       CLI: 0 ms bootstrap, arg table, --run-for, --debugger
```

## Testing

```bash
.venv/bin/pytest                    # everything
.venv/bin/pytest tests/test_lua.py  # just the CLI-level Lua tests
```

Three layers:

- `tests/test_timers.py` — pure-asyncio timer unit tests (no lupa)
- `tests/test_engine.py` — message round-trips through a real lupa VM
- `tests/lua/*.lua` — end-to-end scripts run through the actual `flua` CLI by
  `tests/test_lua.py`

A `tests/lua/` test script uses the shared harness and ends with `t.done()`:

```lua
local script_dir = (arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

t.expect_eq(1 + 1, 2, "math works")

setTimeout(function()
  t.expect(true, "timer fired")
  t.done()
end, 50)
```

`t.done()` prints a summary and exits 0 (pass) or 1 (fail); the runner asserts
the exit code and the `all passed` marker. Every `test_*.lua` script in
`tests/lua/` is discovered automatically — `helpers.lua` is the shared harness
and `arg_roundtrip.lua` is run explicitly.

## Virtual time

Timers run on the engine's virtual clock, and `os.time()` / `os.clock()` /
`os.date()` (and `_PY.now()`) read that clock. Modes, via CLI flags:

- `--speed 1` (default) — realtime; virtual time tracks the wall clock
- `--speed N` — virtual time runs N times faster; timers fire at the correct
  virtual deadline, so absolute-time math stays consistent
- `--instant` — timers fire immediately and virtual time jumps to each
  timer's deadline: a script that waits for days of simulated time completes
  in milliseconds with `os.time()` showing the corresponding future time

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
```

Format: `--%%name:value` (scalar) or
`--%%name:sub1=val1,sub2=val2,...` (subparameters). Values may be booleans,
numbers, `nil`, quoted or bare strings.

Parameters are either **global** or **local**:

- **Local** (everything not listed below) stay on the QA's own `config` —
  e.g. `--%%name:qa1` gives that QA `config.name`.
- **Global** (`speed`, `instant`, `maxhours`, `time`) are copied up to the
  shared config and apply engine-wide; the **last file that sets one wins**.
  They are also visible on every QA's `config`.

The global config is exposed to Lua as `_FLUA.config`.

The engine understands these (CLI flags override annotations):

- `speed` / `time.speed` — virtual time speed (`--speed N`)
- `instant` / `time.instant` — instant mode (`--instant`)
- `maxhours` / `time.hours` — stop after N **virtual** hours
  (`--max-hours H`); the safety valve for accelerated/instant runs of code
  that never ends

```bash
.venv/bin/flua script.lua          # honors the file's annotations
.venv/bin/flua --speed 5 script.lua # CLI wins over the file
```

## Debugging (mobdebug)

flua bundles [MobDebug](https://github.com/pkulchenko/MobDebug) (v0.801, MIT,
vendored unmodified) so VS Code (Lua/mobdebug extension) or ZeroBrane Studio
can debug flua scripts remotely:

```bash
.venv/bin/flua --debugger script.lua       # port 8172 (default)
.venv/bin/flua --debugger 8173 script.lua  # custom port
```

- The debugger attaches before the script runs; script files are loaded via
  `loadfile` with their real path, so breakpoints match file locations
- If no IDE is listening, mobdebug prints a connect error and the script
  runs normally

**Stopped time.** mobdebug pauses the program by blocking in a socket receive
inside the debug hook. Because flua's socket layer is synchronous (see
below), a pause blocks the main thread and freezes the asyncio loop — no
timer callbacks fire while paused — and the virtual clock stands still: the
freeze is noted just before the debugger's blocking receive, and the next
pump tick advances time only up to the freeze point. Absolute-time math
therefore stays consistent — a timer due in 10 virtual seconds still fires
10 virtual seconds after the pause, not "10 seconds minus however long you
stared at the debugger".

### LuaSocket subset

mobdebug needs synchronous sockets, provided by `require("socket")` — a
LuaSocket-compatible subset over plain Python blocking sockets
(`src/flua/sync_socket.py`):

- `socket.tcp()` — `connect`, `settimeout` (nil = block, 0 = non-blocking,
  t = seconds), `send(data[, i[, j]])`, `receive(pattern)`, `close`,
  `getsockname`; patterns `*l`, `*a`, byte counts; LuaSocket return
  conventions (`nil, "timeout", partial` / `nil, "closed", partial`)
- `socket.bind(host, port)` + `server:accept()` — for `mobdebug.listen()`
  server mode
- not implemented: `socket.sleep`, UDP, HTTP, `select`

These calls run on the main thread and may block the asyncio loop — that is
the one deliberate exception to flua's message-passing model, and it is what
makes debugger pauses freeze time. All other I/O stays on the message model.

## Differences from plua

- No FastAPI subprocess, no network clients, no Fibaro emulator, no REPL,
  no telnet — only the engine + timer core.
- plua calls `_PY.timerExpired(id)` directly from timer callbacks; flua
  delivers a `timerExpired` message through the pump instead. The call shape
  is identical but the entry is single and the protocol is serializable.
- Timer IDs are Lua callback IDs (integers), not UUIDs.
- Keep-alive is computed entirely on the Python side
  (`engine.has_pending_work()`), not by Lua-side counters.
