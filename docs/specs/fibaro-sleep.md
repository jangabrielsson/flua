# fibaro.sleep(ms) — design note

Status: implemented. This documents the mechanics and the per-message-type
delivery decisions.

## Goal

`fibaro.sleep(ms)` suspends the **calling QA** for `ms` of virtual time —
other QAs keep running. While a QA sleeps, messages destined for it (timer
callbacks, device actions, UI events, network results, refreshState events,
custom events) are **queued** and delivered — in arrival order — after the
sleeping callback resumes. A restart drops the queue (the deferred messages
belong to the old code instance).

## Why coroutines

All QAs share one Lua VM; a QA callback runs to completion inside
`_PY.dispatch(batch)` on the pump thread (the single-entry discipline). A
blocking sleep would freeze every QA. Instead, each QA callback runs in a
small coroutine (`runInQa`): `fibaro.sleep(ms)` is `coroutine.yield(ms)`, and
the runner schedules a **QA-attributed wake timer** through the existing
timer machinery. The wake resumes the coroutine; the single-entry discipline
still holds (resume happens inside dispatch). Because the wake is an ordinary
timer, sleep rides the virtual clock: `--speed` accelerates it, `--instant`
collapses it, a paused debugger freezes it.

## Which message types defer (are queued) where

Every Python→Lua message funnels through `_FLUA.dispatch(batch)` →
`handlers[msg.type](msg)`. Each handler knows its QA:

| message | QA from | while that QA sleeps |
|---|---|---|
| `timerExpired` | `callback_qas[id]` (registered in `_FLUA.setTimeout`) | queued — except wake timers (`wakeTimers[id]`), which end the sleep; the callback stays registered and runs from the queue |
| `deviceAction` | device id → `qaForDevice` (children resolve to the parent — they share its code) | queued |
| `uiEvent` | `msg.deviceId` → `qaForDevice` | queued |
| `httpResult`/`tcpResult`/`udpResult`/`wsEvent` | `msg.qa` | queued |
| `mqttEvent` | `msg.qa` | queued |
| `customEvent` | broadcast over `qaInstances` | per-QA: one queue entry per sleeping QA |
| `refreshStateEvent` | broadcast over `_FLUA.refreshStateListeners` (maps handle → qaId) | per-QA: one queue entry per sleeping QA (deduped across its subscriber handles) |
| `startQA`/`restartQA` | `msg.id` | **not queued** — restart abandons the sleep *and the queue*; the wake timer was already cancelled Python-side |
| `runPreamble` | main state, no QA | n/a |

The wake resumes the sleeping callback first, then drains the queue —
deferred events run in arrival order after the code that slept. If a
resumed callback (or a deferred handler) sleeps again, its sleep chains
through the same machinery and the queue keeps waiting. Broadcasts are
delivered per-QA on drain (re-dispatching through the shared handler would
hand a second copy to every QA).

## Where the changes live

**`src/flua/lua/init.lua`**

- `callback_qas` (timer id → qaId), `sleeping` (qaId → `true` while a sleep
  is active), `wakeTimers` (wake timer ids, never deferred), `workQueues`
  (qaId → FIFO of deferred messages).
- `runInQa(qaId, fn, ...)` — the coroutine wrapper around every QA callback
  entry point; `qaId == nil` means a runtime timer and runs plain (sleep
  errors there). The runner mirrors the current thread's debug hook onto the
  callback coroutine (`debug.gethook`/`debug.sethook`): this Lua build does
  not inherit hooks into new coroutines, and without the mirror mobdebug
  breakpoints/stepping would silently stop firing inside callbacks.
- `resumeQa(qaId, co, ...)` — resume + error containment (`debug.traceback`
  on the coroutine); a `number` yield marks the QA sleeping and schedules the
  wake timer; any other yield is a protocol violation error. (The wake-timer
  id is declared separately from its assignment: a closure inside a
  `local id = ...` initializer binds to an outer id in this Lua version.)
- `processWork(qaId)` / `deliverQueued(qaId, msg)` — the drain, run after
  each wake: FIFO messages are delivered while the QA is awake; a deferred
  handler that sleeps again suspends the drain until its own wake.
- Each handler in the table above gained its queue check / per-QA queue.

**`src/flua/lua/fibaro.lua`** — `fibaro.sleep(ms)`:
`__assert_type` → `coroutine.running()` check (clear error at top level) →
`_FLUA.qa(_FLUA.qaId)` check (clear error during init, before the instance
exists) → `coroutine.yield(ms)`. The old blocking `_PY.sleep` stub was
removed (it did not exist on the Python side and would have errored).

**`src/flua/lua/quickapp.lua`** —
`RefreshStateSubscriber:run()` registers `handle -> _FLUA.qaId` so refresh
delivery can be deferred per sleeping QA.

**`src/flua/engine.py`** — no changes needed: the wake timer is a normal
QA-attributed timer, so `--speed`/`--instant`/`has_pending_work` behave
unchanged, and `exit()`/`restart_qa()` cancel it via `cancel_qa`.

## Edge cases

- **exit() while sleeping** — impossible from the QA itself (no code runs);
  the wake timer is cancelled by `cancel_qa`. A stale queue entry for a dead
  QA is harmless (nothing drains it; `qaInstances` entries linger the same
  way).
- **restartQA while sleeping** — `sleeping[id]` and `workQueues[id]` are
  cleared, the old coroutine is abandoned, the new instance boots normally.
- **sleep at top level** — hard error, not a silent no-op. In `onInit` it
  works: flua defers the main QA's onInit to a 0ms timer after the instance
  is registered (children's onInit stays synchronous); an onInit error still
  fails the load.
- **children** — a sleeping child defers its parent QA (the code that
  handles its events), like the HC3's shared instance thread.
- **nested sleep** — a callback that sleeps again after waking re-arms
  through the same path; deferred messages keep their FIFO order across
  chained sleeps.
- **intervals** — a deferred tick runs on wake and reschedules from there:
  intervals effectively pause during a sleep.
- **sleep inside `async.run`** — the async runner sees a non-awaitable yield
  and reports it (`async.await` yields a function, `fibaro.sleep` a number).
- **reentrancy** — while sleeping, no Lua runs for that QA (single entry);
  drain and resume only happen inside dispatch.

## Tests (`tests/test_sleep.py`)

- sleep suspends only the calling QA; a timer of that QA firing during the
  sleep runs after the sleeping callback resumed (arrival order); the other
  QA's timer is unaffected.
- device action arriving during the sleep is delivered after the
  continuation.
- sleep works in `onInit` (deferred until the instance registers); messages
  during an onInit sleep queue; an onInit error still fails the load.
- `--instant` (speed=inf) collapses the sleep.
- `fibaro.sleep` at top level errors and fails the QA load.
- error in the code after the sleep is contained and printed.
- restart during sleep drops the deferred queue and the pending sleep.
- `examples/sleep.lua` runs end to end and keeps its deferred timer.
