# flua concurrency & threading model

The runtime's ground rules for *who runs where* and *who may wait for what*.
This is the doc to read before touching the pump, the bridge, timers, or the
graceful-exit path — most of it was learned the hard way (see the two race
lessons at the end). Component-level orientation lives in ARCHITECTURE.md;
this is the execution model underneath it.

## The big picture

Everything runs on **one asyncio event loop** (the CLI's `asyncio.run` loop in
tests, `cli.py::_run` in production). On top of that loop sit:

- **The pump** — one asyncio task (`flua-pump`, `engine.py::_pump`), the only
  thing that enters Lua. It loops forever: tick the virtual clock, fire due
  timers, drain inbound messages, deliver outbound batches to Lua.
- **The Lua runtime** — lupa, a single Lua state. All QAs share it, isolated
  by per-QA environments and per-QA coroutines.
- **Per-QA coroutines** — every QA callback runs in its own Lua coroutine
  (`lua/init.lua::runInQa`). A coroutine suspends itself (sleep, remote API
  call) without blocking anything else.
- **Worker threads** — a handful of plain `threading.Thread`s for blocking
  I/O (the real HC3, sockets). They never touch Lua directly; they post
  results back through thread-safe sinks.

```
                        one asyncio event loop
   ┌──────────────────────────────────────────────────────────────────┐
   │  CLI keep-running poll (50 ms)                                    │
   │  flua-pump task:  tick clock → fire timers → drain inbound →      │
   │                    deliver outbound batch → Lua dispatch          │
   │  flua-hc3-poll task (online): long-poll refreshStates (daemon th.) │
   │  flua-http / flua-tcp / flua-mqtt asyncio tasks (tracked)         │
   └───────────────▲─────────────────────────────────▲────────────────┘
         _inbound │ (deque, _PY.post)      _outbound │ (asyncio.Queue,
                   │                                  enqueue_outbound)
   ┌───────────────┴─────────────┐   ┌────────────────┴───────────────┐
   │ Lua side (single state)     │   │ Python side                    │
   │  per-QA coroutines:         │   │  engine handlers (one per msg) │
   │   sleep/API suspend+defer   │   │  worker threads:               │
   │   _FLUA.dispatch(batch)     │   │   flua-api (remote api calls)  │
   └─────────────────────────────┘   │   flua-hc3-poll (daemon)       │
                                     │   net/ws/mqtt receivers        │
                                     └────────────────────────────────┘
```

## The message plumbing

- **Lua → Python** (`_inbound`, a `collections.deque`): `_PY.post(msg)` appends
  and returns immediately. Never blocks, never calls Lua.
- **Python → Lua** (`_outbound`, an `asyncio.Queue`): `engine.enqueue_outbound`
  calls `put_nowait` — safe from any thread. The pump drains it.
- **Single-entry discipline**: Lua is entered only from
  `engine._deliver_to_lua(batch)` → `_FLUA.dispatch(batch)`. Nothing else may
  call into Lua — not worker threads, not `has_pending_work()`, not fixtures.
  (One deliberate exception: the debugger's mobdebug sockets block the loop
  by design; see blocking rules.)
- **Wire format**: everything crossing the bridge is a JSON-compatible dict
  (`messages.py`). Lua function references must never cross.

## The pump loop

`engine.py::_pump` (wake every `_PUMP_POLL = 0.01` s):

1. `clock.tick(time.monotonic())` — advance virtual time by real elapsed.
2. `self._timers.fire_due()` — fire every virtual-time timer whose deadline
   passed; each fire enqueues a `timerExpired` message.
3. `await self._drain_inbound()` — dispatch Lua→Python messages to their
   handlers (setTimeout registration, logs, api calls, exit…).
4. Get one outbound batch (`get_nowait()`) and drain the queue fully, then
   `_deliver_to_lua(batch)` — **synchronously**, the loop is frozen while
   Lua runs.
5. Idle: `_flush_db()` (dirty-guarded) and sleep 10 ms.

The batch is the atomic unit of delivery. Order within a batch and across
batches is FIFO; this is what guarantees "the greeting prints before QA
output" and "a resumed QA runs before its deferred messages".

## Per-QA coroutines and the suspend machinery

`lua/init.lua` keeps per-QA state in plain tables:

- `qaRunners[qaId]` — the QA's current callback coroutine.
- `sleeping[qaId]` — the QA is suspended (sleep or remote API call); its
  messages defer instead of running.
- `workQueues[qaId]` — FIFO of messages deferred while sleeping.
- `pendingApi[qaId]` — the coroutine awaiting an `apiResult`.
- `wakeTimers[id]` — timer ids that end a sleep (never deferred).

**`fibaro.sleep(ms)`**: the callback coroutine `coroutine.yield(ms)`s; the
runtime registers a wake timer, marks `sleeping[qaId] = true`. While asleep,
any message for the QA is queued in `workQueues`; when the wake timer fires,
the sleeping callback resumes *first*, then its deferred queue drains.

**Remote `api.*` (online/proxy mode)**: the callback yields an `apiCall`
message; the engine spawns a `flua-api` worker thread that runs the HTTP
request (the pump keeps going — other QAs keep running). The response comes
back as an `apiResult` message that resumes the QA's coroutine. Only the
*calling* QA suspends.

## Worker threads and tracked work

| Thread / task | What it does | Blocking? | Counted as pending work? |
|---|---|---|---|
| `flua-pump` (task) | the loop above | Lua dispatch freezes the loop | — |
| `flua-hc3-poll` (task + daemon thread) | refreshStates long poll; mirrors events | no (request on a daemon thread, result via `call_soon_threadsafe`) | deliberately **no** (documented) |
| `flua-api` (thread) | a suspended QA's remote api call | the HC3 round trip | **yes** — `_api_calls_inflight` |
| `flua-http` (task via `asyncio.to_thread`) | `net.HTTPClient` requests | no | yes — `_http_tasks` |
| net/ws/mqtt receiver threads | socket reads | no | yes — connection counts |
| `flua-proxy-connect` (thread) | proxy CONNECT handshake | no | via proxy tasks |

**Rule: anything a suspended QA can be waiting on must be counted by
`has_pending_work()`.** A worker that isn't counted is a hole the
graceful-exit check will eventually fall through (see race lesson 2).

## Blocking rules

- **The pump must never block on I/O.** QA `api.*` calls suspend and move to
  `flua-api`; `net.HTTPClient` moves to `flua-http`; sockets to their
  receiver threads.
- **`Api._dispatch_lock` may be held across a remote HTTP call.** A handler
  that forwards to the real HC3 (`req.remote`) holds the dispatcher's RLock
  for the whole round trip. A second QA's *boot-time* API call queues behind
  that lock — this is why `test_slow_remote_call_does_not_freeze_other_qas`
  delays the slow call until the other QA has booted. Sim-side work is
  microseconds; contention is rare by design.
- **Engine-side remote calls and the debugger still block the pump.** Keep
  them LAN-local and rare (`--api` flags, mobdebug sockets).
- **`has_pending_work()` may run on any thread at any time.** It only reads;
  it must never call Lua or take locks that a worker might hold.

## Graceful exit

The CLI (`cli.py::_keep_running`) polls every 50 ms and exits when the run
is done. Pending work is:

```
timers ∪ keep-alive QAs ∪ _inbound ∪ _outbound ∪ _http_tasks
∪ ws/mqtt connections ∪ in-flight flua-api calls
```

with overrides: `--%%keep-alive:true` QAs (online only) hold the run open,
`--ui` holds it open, `--run-for N`/`--%%maxhours` bound it in virtual time,
and `exit(code)` from a QA sets the process exit code (last failing QA wins).

## Two race lessons (do not regress these)

1. **Never cancel a pending `Queue.get()`.** The pump used
   `asyncio.wait_for(self._outbound.get(), timeout=...)`; on Python ≤ 3.12 a
   message arriving exactly as the timeout fired was consumed and *discarded*
   (TimeoutError swallowed the item). Lost timer/restart/API messages made
   runs end early under load — the CI failures of 0.1.36. The pump now uses
   `get_nowait()` + a 10 ms sleep; `get_nowait()` cannot lose an item. If you
   add another timeout, use polling, not cancellation.

2. **Count every worker a suspended QA waits on.** `flua-api` threads were
   untracked, so `has_pending_work()` could report idle mid-call and the CLI
   exited before the response resumed the QA (reproduced on 3.12 CI and 3.15
   under load). `_api_calls_inflight` (increment before thread start,
   decrement in `finally`) closed it. New worker types need the same
   treatment: track → count → verify with a load test.

## Shutdown

`engine.stop()` sets `_running = False`, cancels the pump/poller/proxy/http
tasks, and awaits the pump task. Worker threads are daemons and are never
joined — a hung HC3 must not delay exit. Workers that finish after teardown
drop their results through `_post_from_worker` (a closed loop = the run is
over). Tests: cancel first, then assert — never sleep for teardown.

## Where the pieces live

- Pump, handlers, worker spawns: `src/flua/engine.py`
- Suspend/defer machinery, dispatch: `src/flua/lua/init.lua`
- Wire format: `src/flua/messages.py`
- Virtual clock, timers (heap, horizon, instant mode): `src/flua/clock.py`,
  `src/flua/timers.py`
- Bridge surface (`_PY`): `src/flua/bindings.py`
