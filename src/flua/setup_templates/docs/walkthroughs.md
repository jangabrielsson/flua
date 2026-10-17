# flua walkthroughs

Guided traces through the runtime's key flows, one mechanism at a time.
Symbol references (`file.py::function`, `lua/init.lua::name`) stay accurate
across line drift; pair with concurrency.md (the execution model) and
invariants.md (the contracts).

## 1. A QA boots

The CLI path (`cli.py::_run`) and the in-engine path (`engine.load_qa_file`,
used by `_FLUA.loadQAfromFile`) converge on the same machinery:

1. **`engine.start_qa`** → `engine._prepare_qa`: assign the id (from 5000,
   skipping taken ids), resolve name/type/properties, and — critically —
   **register the QA as a device in the sim before any code runs**
   (`api/state.py::register_qa`, which also records the
   `DeviceCreatedEvent`). Proxy QAs resolve their HC3 device first and run
   under *its* id.
2. `_prepare_qa` enqueues a `startQA` message, and the CLI path then calls
   `_FLUA.startQaFile` directly; both end in `lua/init.lua::runQa`, which
   schedules the boot as the QA's own **0 ms timer** — every boot rides the
   pump, so nothing re-enters Lua mid-dispatch.
3. `lua/init.lua::startQaInEnv`:
   - builds the per-QA environment (`qaEnvFor`: isolated globals, `_G`,
     `package`, per-QA `_FLUA` with its own qaId/config/arg);
   - evaluates `--%%var` expressions and posts `qaVars`;
   - loads extra `--%%file` files, then the main chunk;
   - registers a stub instance (`qaInstances[qaId]`) **before the chunk
     runs**, so a top-level `fibaro.sleep` can already resolve the QA.
4. **`bootstrapQa`** constructs the `QuickApp` from `_PY.device_for(qaId)`
   (the same device the API serves — no bridge mismatch), merges `--%%var`
   values into `quickAppVariables`, and constructs the instance —
   `QuickApp:__init__` runs `onInit` synchronously, then
   `initChildDevices`.
5. **`initChildDevices` calls `api.get('/devices?parentId=…')`.** Offline
   this is a fast sim read. Online, it *suspends the boot coroutine* like
   any remote call — which is why a QA starting while another QA's remote
   call holds the dispatch lock waits for it (the discovery behind
   `test_slow_remote_call_does_not_freeze_other_qas`'s 200 ms delay).
6. Finally `qaLoaded` is posted and the Python-side QA directory marks the
   QA loaded.

Ordering guarantee this depends on: the device exists before `onInit`
(`engine._prepare_qa` comment), `__TAG` is bound before the files execute,
and `onInit` runs before `initChildDevices` (the HC3 order).

## 2. `fibaro.sleep` suspends one QA, defers its messages

All in `lua/init.lua` (see concurrency.md for the table layout):

1. The callback coroutine calls `fibaro.sleep(ms)` → `coroutine.yield(ms)`.
2. `resumeQa` sees a number: sets `sleeping[qaId] = true` and registers a
   **wake timer** (`wakeTimers[id] = true` — never deferred).
3. Every message for the QA while asleep (timers due, device actions,
   refresh events) goes through `queueFor` into `workQueues[qaId]` instead
   of running.
4. The wake timer fires → `handlers.timerExpired` special-cases wake
   timers: `sleeping[qaId] = nil`, then `resumeQa(qaId, co)` — the sleeping
   callback finishes **first** — then `processWork(qaId)` drains the
   deferred queue in order.

Two consequences pinned by tests: a timer due during the sleep runs *after*
the sleeping callback (not during), and a QA restart while asleep drops the
deferred queue and cancels the wake timer (`tests/test_sleep.py`).

## 3. A remote `api.*` call suspends only the calling QA

1. `lua/init.lua::apiCall` — the QA's `api.get` wrapper — checks
   `_PY.api_remote_mode()` **and** that the call runs in the QA's own
   callback coroutine. Both true → `coroutine.yield{type="apiCall", …}`.
   (Anywhere else — nested coroutines, non-QA code — the call stays
   synchronous.)
2. `resumeQa` recognizes the `apiCall` yield: `sleeping[qaId] = true`,
   `pendingApi[qaId] = co`, `_PY.post(apiCall)`.
3. The engine's `_handle_api_call` bumps `_api_calls_inflight` and spawns a
   **`flua-api` worker thread** running `Api.dispatch` — the pump never
   blocks, every other QA keeps running.
4. Caveat: `Api._dispatch_lock` serializes dispatches and **may be held
   across a remote HTTP call** (a forwarding handler holds it). Another
   QA's sim-side call queues behind it — microseconds normally, but a boot
   racing a slow remote call waits (walkthrough 1, step 5).
5. The worker finishes → `messages.api_result` →
   `_post_from_worker` (drops the result if the loop is closed) → pump →
   `handlers.apiResult` resumes the coroutine with `(data, status)`.

`_api_calls_inflight` keeps the graceful-exit check honest while the call is
in flight (race lesson 2 in concurrency.md).

## 4. A refreshStates event reaches a subscriber

Two delivery channels, one contract (record + emit):

1. **Record into the feed**: a handler (e.g. `updateProperty`,
   `globals_create`, `device_delete`) calls a `SimState.record_*` method —
   `api/state.py` appends `(seq, entry)` with a strictly increasing seq and
   the real HC3's envelope (`type/created/createdMillis/sourceType/objects/
   data`; global-variable events use the lighter envelope).
2. **Emit to the pump**: the handler calls
   `req.emit(messages.refresh_state_event(entry))` →
   `Api._emit` → `engine.enqueue_outbound`.
3. The pump delivers `refreshStateEvent` → `lua/init.lua::
   handlers.refreshStateEvent` iterates `_FLUA.refreshStateListeners` —
   handles registered by `RefreshStateSubscriber:run()` (`quickapp.lua`) —
   and calls each handle (deferring for sleeping QAs).
4. **Poll channel**: `api.get('/refreshStates?last=N')` serves the recorded
   feed (`routes/system.py::refresh_states`) — `last` semantics, changes vs
   events split, base fields always present.
5. **Online mirror**: the `flua-hc3-poll` task long-polls the real HC3 and
   `_mirror_event`s each entry — local seq, same content, then the same
   pump emit — so sim and HC3 events are indistinguishable downstream.
   Proxy devices never emit locally (the HC3's own event arrives through
   this path).

## 5. Proxy mode shadows an HC3 device

`--%%mode:proxy` (online only): the real HC3 owns the device; the sim
shadows it under the *same id*.

1. **Deploy/reuse**: `proxy.py::resolve_proxy` uploads the QA as
   `<name>_Proxy` on the HC3 (or reuses the existing one; wrong-type
   proxies are deleted and recreated). Its HC3 id becomes the QA's id.
2. **Shadow**: `api/state.py::mark_proxy(id)` flags the id;
   `register_qa(proxy=True)` skips the local `DeviceCreatedEvent` (the HC3
   emits its own, mirrored by the poll). Existing proxy children are
   shadowed via `register_proxy_child` under their HC3 ids.
3. **Updates**: mutating API calls on the device call `forward_to_proxy` —
   the HC3 gets the real update; the sim records no local event (the HC3's
   event comes back through the poll). `useUiView` is only pushed when the
   QA declares it; otherwise the HC3's own UI config wins.
4. **Callbacks**: the emulator's callback server receives the proxy's
   actions/UI events over HTTP; they dispatch with `external=True`, which
   is why the sim must not double-record them (`action_device` skips the
   local event for proxy devices).
5. **CONNECT**: at startup the emulator tells the proxy where to listen
   back, so an existing proxy always points at the current run. The proxy
   QA implies keep-alive — the emulator must stay up to serve callbacks.

Pins: `tests/test_proxy.py` (id reuse, no-duplicate events, mirroring,
callback routing).
