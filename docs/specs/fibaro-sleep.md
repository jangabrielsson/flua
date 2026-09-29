# fibaro.sleep(ms) — design note

Status: implemented. This documents the mechanics and the per-message-type
delivery decisions.

## Goal

`fibaro.sleep(ms)` suspends the **calling QA** for `ms` of virtual time —
other QAs keep running. The QA behaves like a busy wait: while it sleeps, **no
callback is delivered to it**. Messages that would target it (timer
callbacks, device actions, UI events, network results, refreshState events,
custom events) are **dropped**, not queued — matching the HC3, where a
blocking sleep means the instance simply never sees events that arrive
during the sleep.

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

## Which message types defer (are dropped) where

Every Python→Lua message funnels through `_FLUA.dispatch(batch)` →
`handlers[msg.type](msg)`. Each handler knows its QA:

| message | QA from | while that QA sleeps |
|---|---|---|
| `timerExpired` | `callback_qas[id]` (registered in `_FLUA.setTimeout`) | dropped — except wake timers (`wakeTimers[id]`), which end the sleep |
| `deviceAction` | device id → `qaForDevice` (children resolve to the parent — they share its code) | dropped |
| `uiEvent` | `msg.deviceId` → `qaForDevice` | dropped |
| `httpResult`/`tcpResult`/`udpResult`/`wsEvent` | `msg.qa` | dropped |
| `mqttEvent` | `msg.qa` | dropped |
| `customEvent` | broadcast over `qaInstances` | per-QA: skipped for sleeping QAs |
| `refreshStateEvent` | broadcast over `_FLUA.refreshStateListeners` (maps handle → qaId) | per-QA: skipped for sleeping QAs |
| `startQA`/`restartQA` | `msg.id` | **not dropped** — restart abandons the sleep (`sleeping[id] = nil`); the wake timer was already cancelled Python-side |
| `runPreamble` | main state, no QA | n/a |

A dropped timer callback also releases its `callbacks[id]` entry (the timer
is spent). A dropped interval tick ends the interval chain — the callback was
lost, so the chain is not rescheduled (consistent busy-wait semantics).

## Where the changes live

**`src/flua/lua/init.lua`**

- `callback_qas` (timer id → qaId), `sleeping` (qaId → suspended coroutine),
  `wakeTimers` (wake timer ids, never deferred).
- `runInQa(qaId, fn, ...)` — the coroutine wrapper around every QA callback
  entry point; `qaId == nil` means a runtime timer and runs plain (sleep
  errors there). The runner mirrors the current thread's debug hook onto the
  callback coroutine (`debug.gethook`/`debug.sethook`): this Lua build does
  not inherit hooks into new coroutines, and without the mirror mobdebug
  breakpoints/stepping would silently stop firing inside callbacks.
- `resumeQa(qaId, co, ...)` — resume + error containment (`debug.traceback`
  on the coroutine); a `number` yield re-arms the sleep, any other yield is a
  protocol violation error. (The wake-timer id is declared separately from
  its assignment: a closure inside a `local id = ...` initializer binds to an
  outer id in this Lua version.)
- Each handler in the table above gained its drop check / per-QA skip.

**`src/flua/lua/fibaro.lua`** — `fibaro.sleep(ms)`:
`__assert_type` → `coroutine.running()` check (clear error at top level) →
`_FLUA.qa(_FLUA.qaId)` check (clear error during init, before the instance
exists) → `coroutine.yield(ms)`. The old blocking `_PY.sleep` stub was
removed (it did not exist on the Python side and would have errored).

**`src/flua/lua/quickapp.lua`** —
`RefreshStateSubscriber:run()` registers `handle -> _FLUA.qaId` so refresh
delivery can skip a sleeping QA.

**`src/flua/engine.py`** — no changes needed: the wake timer is a normal
QA-attributed timer, so `--speed`/`--instant`/`has_pending_work` behave
unchanged, and `exit()`/`restart_qa()` cancel it via `cancel_qa`.

## Edge cases

- **exit() while sleeping** — impossible from the QA itself (no code runs);
  the wake timer is cancelled by `cancel_qa`. A stale `sleeping` entry for a
  dead QA is harmless (nothing is delivered to it; `qaInstances` entries
  linger the same way).
- **restartQA while sleeping** — `sleeping[id]` cleared, old coroutine
  abandoned, new instance boots normally.
- **sleep at top level / in onInit** — hard error, not a silent no-op.
- **children** — a sleeping child sleeps its parent QA (the code that
  handles its events), like the HC3's shared instance thread.
- **nested sleep** — a callback that sleeps again after waking re-arms
  through the same path.
- **sleep inside `async.run`** — the async runner sees a non-awaitable yield
  and reports it (`async.await` yields a function, `fibaro.sleep` a number).
- **reentrancy** — while sleeping, no Lua runs for that QA; resume only
  happens inside dispatch.

## Tests (`tests/test_sleep.py`)

- sleep suspends only the calling QA; a timer callback of that QA firing
  during the sleep is lost, the other QA's timer runs.
- device action arriving during the sleep is lost; after wake, actions are
  delivered again.
- `--instant` (speed=inf) collapses the sleep.
- `fibaro.sleep` at top level errors and fails the QA load.
- error in the code after the sleep is contained and printed.
