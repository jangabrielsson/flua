# flua — architecture

This file explains how flua works under the hood. The user guide is
[USAGE.md](USAGE.md); this is the machinery. Diagrams are ASCII so they
render everywhere (GitHub, VS Code, terminal).

## 1. Overview

flua runs real Fibaro QuickApps offline. One Python process hosts a lupa
runtime (Lua 5.x) and an asyncio event loop:

- **Lua side** — the HC3 runtime: `QuickApp` classes, `fibaro`, `api`, `net`,
  `mqtt`, timers. Each QA runs in its own Lua environment (isolated globals).
- **Python side** — the engine: message pump, virtual clock, the simulated
  HC3 (or the real one online), and worker threads for blocking I/O.
- **The bridge** — a strict message-passing protocol. Lua never calls
  Python in a way that could re-enter Lua, and Python never calls Lua
  except from one place.

```
                 +---------------------------- flua process ----------------------------+
                 |                                                                     |
  QA files ----> |  CLI (argparse, --%% parsing, mode peek)                            |
                 |    |                                                                |
                 |    v                                                                |
                 |  LuaEngine --------------------------------------------------       |
                 |  | lupa LuaRuntime  |  virtual clock   |  api (sim/HC3)     |       |
                 |  | inbound deque    |  TimerManager    |  qa_* worker pools |       |
                 |  | outbound queue   |  env chain       |  Hc3Remote (online)|       |
                 |  | pump task (THE single Lua entry point)                    |       |
                 |  +-----------------------------------------------------------+       |
                 |        ^ post(msg)                    | enqueue_outbound(msg)          |
                 |        |                              v                              |
                 |   Lua QAs (per-QA envs)          worker threads                      |
                 |   quickapp/fibaro/net/mqtt       urllib / sockets / RFC6455 / MQTT 3.1.1
                 |                                                                       |
                 +-----------------------------------------------------------------------+
```

## 2. The single-entry discipline

The one rule everything else follows: **the pump is the only code that
enters the Lua VM, and it never does so while Lua is on the stack.**

- Lua → Python traffic is **append-only**: Lua code calls `_PY.*` bridges,
  which append plain messages to the inbound deque and return immediately.
  No Python handler ever calls Lua directly.
- Python → Lua traffic is **queued**: handlers push messages onto the
  outbound queue; the pump delivers them as a batch through
  `_FLUA.dispatch`.
- Consequences: no reentrancy hazards, messages are serializable
  JSON-shaped dicts, and timers/actions/callbacks all share one delivery
  path.

The two deliberate exceptions, both documented:

1. **Log lines print directly** (`_PY.log`) — writing to stdout touches no
   Lua state, so it is safe at any call depth, including inside
   debugger-stepped code where the pump is frozen.
2. **The debugger's sockets block the main thread** — that is what makes a
   mobdebug pause freeze the pump and the virtual clock.

## 3. Message flow

```
  Lua code                     Python engine                       Lua runtime
  ---------                    --------------                      ------------

  _PY.post({type=...})         inbound deque                       
      ----------------------->  |                                  
                                v  pump loop:                      
                                |  tick(clock)                     
                                |  timers.fire_due()               
                                |  drain inbound -> handler        
                                |     (api, timers, worker spawn)  
                                |  outbound.get() -> batch         
                                |---------------------->  _FLUA.dispatch(batch)
                                |                             handlers[msg.type](msg)
                                |                             (timer fires, callbacks,
                                |                              QA bootstrap, ...)
```

Every message is a dict with a mandatory string `type`. Functions never
cross the bridge — callbacks are registered Lua-side by integer id. The
full type list lives in `src/flua/messages.py`; adding one means a handler
in `engine.py` (inbound) and/or `lua/init.lua` (outbound).

## 4. Layers

```
src/flua/
  cli.py           argument parsing, --%% config assembly, mode peek (--%%offline),
                   --run-for / --watch / --check / export / unpack
  engine.py        LuaEngine: lupa VM, queues, pump, QA lifecycle, worker pools,
                   the HC3 poller, the auth-lockout guard
  api/             the REST surface: one dispatcher, two backends
    __init__.py      Api.dispatch: regex route table -> handlers -> hybrid forward
    state.py         SimState: devices/rooms/scenes/globals, change & event feeds
    routes/*.py      pure handlers: (state, request) -> (data, status)
  hc3.py           Hc3Remote: blocking urllib client, basic auth, raw-body import
  http.py          urllib-based blocking HTTP (worker threads)
  websocket.py     minimal RFC 6455 client (stdlib sockets + ssl)
  mqtt.py          minimal MQTT 3.1.1 client (stdlib sockets + ssl)
  sync_socket.py   blocking LuaSocket-compatible TCP/UDP (the debugger's sockets)
  devices/         the HC3 device catalog (176 real captures) + skeleton builder
  config.py        --%% annotation parsing, EOH, the offline peek, env helpers
  environment.py   the os.getenv chain: local .env > ~/.env > process env
  timers.py        TimerManager on the virtual clock (per-QA attribution)
  clock.py         VirtualClock: realtime / accelerated / instant, start time
  messages.py      message type constants + builders
  bindings.py      the _PY table (post, log, api, api_hc3, net/mqtt entry points)
  lua/init.lua     the Lua runtime: sanitizer, log, timers, dispatch, QA bootstrap
  lua/quickapp.lua the QuickApp/QuickAppBase/QuickAppChild classes
  lua/fibaro.lua   the fibaro API (HC3-compatible)
  lua/net.lua      HTTPClient, TCPSocket, UDPSocket, WebSocketClient(+Tls)
  lua/mqtt.lua     mqtt.Client, mqtt.QoS, the documented event API
```

## 5. The Lua runtime (`lua/init.lua`)

- **Sanitizer.** Every `_PY.post` payload passes through a UTF-8 sanitizer:
  invalid bytes are hex-escaped, so binary strings (like `utf8.charpattern`)
  cross lupa's strict decode without killing the process. Log lines go
  through the same sanitizer before `_PY.log`.
- **Per-QA environments.** Each QA gets its own `_FLUA` (qaId/config/arg)
  whose metatable falls through to the shared engine table; runtime libs
  are loaded into the QA's env before its code.
- **Bootstrap.** `startQaInEnv` is the shared QA boot: merge `.flua.lua`,
  evaluate `--%%var` expressions (`load("return "..expr, nil, "t", {config, os})`),
  load extra files, pcall the chunk, construct the QuickApp instance.
- **Dispatch.** `handlers.*` deliver timers, actions, net/mqtt results,
  refreshStates events, QA restarts, and `-e` preambles.

## 6. The REST dispatcher (`api/`)

One dispatcher, three outcomes:

```
  api.get(path) -> Api.dispatch
    |-- /quickApp/*      engine-backed QA file management (local only)
    |-- route table      pure handlers over SimState -> (data, status)
    |       |-- matched 404 + online + entity id < 5000 -> forward to the HC3
    |       '-- matched 404 + flua id (>= 5000)          -> local 404, never forward
    '-- no route + online                                -> forward to the HC3
```

- **Id namespaces**: 5000+ = flua QAs and runtime-created devices (always
  local); below 5000 = the HC3's namespace (forwarded online). This is what
  makes `fibaro.getValue(self.id, ...)` work in both modes.
- **`--%%offline:true`** on a QA pins its `api.*` calls to the sim (the
  calling QA's id travels with each request).
- **`api.hc3.*`** forces the remote backend (bypasses hybrid routing;
  `fibaro.callhc3` uses it). Offline it stands in for the sim.
- **Events.** State changes emit `DevicePropertyUpdatedEvent` /
  `DeviceActionRanEvent` with the real HC3's envelope; `updateProperty`
  emits only when the value actually changes. Configuration edits go to
  the `changes` feed instead.

## 7. Worker threads

All blocking network I/O runs in worker threads; the pump never blocks:

```
  Lua post {httpRequest|tcp*|udp*|ws*|mqtt*}
    -> handler spawns an asyncio task
       -> asyncio.to_thread(blocking op) on a dedicated pool
          -> result -> enqueue_outbound  (thread-safe hop: call_soon_threadsafe)
             -> pump -> dispatch -> per-QA net/mqtt handlers -> callbacks
```

In-flight work counts as **pending work** — the process stays alive until
timers, queues, and open connections are all done. The debugger's sockets
are the one main-thread exception (see §2).

## 8. Virtual time

Timers run on `VirtualClock` (virtual seconds, epoch-aligned). Modes:
realtime, `--speed N` accelerated, `--instant` (timers fire now, time jumps
to each deadline). `os.time()`/`os.date()` read the virtual clock (whole
seconds); `os.clock()` stays the real runtime clock; `_FLUA.millitime()`
is virtual milliseconds. `--start "2027/12/31 23:59:50"` sets the origin,
so date logic can be tested at New Year, leap days, DST changes — and the
debugger pause freezes the clock (the freeze is noted around the blocking
receive).

## 9. Config pipeline

```
  raw file header  ->  peek_offline()        (mode decision, pre-engine)
  full source      ->  parse_annotations()   (post-engine, per QA)
  per-QA config    <-  CLI flags + globals + locals + .flua.lua base
  --%%var:name=expr   ->  evaluated in Lua with {config, os} in scope
  os.getenv(name)     ->  EnvChain: local .env > ~/.env > process env
```

The `.fqa` export/import round-trip reuses the pipeline: unpacked files
carry generated `--%%` headers, so imports load like any other QA.

## 10. Online mode (`--api remote`)

`Hc3Remote` (stdlib urllib) speaks basic auth and the **raw-body import
transport** (`POST /quickApp/` with the fqa JSON string — the swagger's
multipart description is misleading; plua verified the real transport).
Two safety rules:

- **The lockout guard**: any 401/403 aborts flua immediately and is never
  retried (the HC3 locks itself after 4 attempts). The poller stops on its
  first auth failure too — it is usually the first caller.
- **The poller** long-polls `/refreshStates` and mirrors the real events
  into the local buffer, so `api.get('/refreshStates?last=N')` serves a
  merged feed and Lua `RefreshStateSubscriber`s receive them through the
  pump.

Mode selection: explicit `--api` > the main QA's `--%%offline:true` (peeked
before the engine starts) > online if HC3 credentials exist in the env
chain > offline.

## 11. The device catalog

QA devices are built from `src/flua/devices/devices.json` — 176 real HC3
device captures, scrubbed of identity/secrets and **array-normalized** at
`devices/skeleton_for` (empty Lua tables serialize ambiguously; the catalog
captured `{}` where the HC3 schema declares `[]`, and that once broke the
real HC3's import). The compat suite (§12) exists to catch exactly this
class of drift.

## 12. Testing map

- **Unit** — pure Python: clock, timers, config parsing, route handlers.
- **Engine** — real lupa VM: message round-trips, QA lifecycle, network
  round-trips against local echo servers / a minimal MQTT broker / an RFC
  6455 server.
- **CLI** — subprocess runs of the actual binary, end to end.
- **Live (opt-in, `HC3_TEST=1`)** —
  `tests/test_hc3_live.py` (lifecycle: read-only + import→call→events→delete,
  lockout-safe) and `tests/test_hc3_compat.py` (shape oracle: the same
  request through the sim and the real HC3 must agree on structure).
- **Isolation** — an autouse fixture isolates `HOME` so a developer's real
  `~/.env` can never flip plain tests into online mode.

## 13. The invariants, in one place

1. Only the pump enters Lua; never with Lua on the stack.
2. Logs print directly (`_PY.log`), never queue.
3. All bridge strings are UTF-8 (sanitizer on the way in).
4. Functions never cross the bridge; callbacks are id-registered.
5. flua entity ids are ≥ 5000 and are always served locally.
6. An auth failure costs exactly one attempt, always.
7. Worker I/O never blocks the pump; open connections are pending work.
8. `updateProperty` emits an event only when the value changes.
9. The debugger's sockets block the main thread on purpose.
10. Tests never touch a production HC3 unless `HC3_TEST=1`.
