# flua invariants & contracts

The behavioral contracts that define "flua works". Each invariant names the
test(s) that pin it — if you change the behavior, the pin is the test to
update (deliberately), and if you want to know what a piece of code must not
break, the pin is the test to run. Companion to concurrency.md (execution
model) and ARCHITECTURE.md (components).

## Identity & ids

- **Engine-assigned QA ids start at 5000** and increment, skipping ids the
  sim already has. Lower ids belong to the HC3's namespace.
  *Pinned by:* `tests/test_qa.py::test_qa_environments_are_isolated`
- **Runtime-created devices draw ids from `FIRST_RUNTIME_ID = 900000`** —
  child devices never collide with QA ids.
  *Pinned by:* `tests/test_api.py::test_create_child_device`
- **A proxy QA runs under its HC3 device id** — the sim shadow and the HC3
  device are the same id, so callbacks route to the right QA.
  *Pinned by:* `tests/test_proxy.py::test_proxy_create_child_device_uses_hc3_id`
- **Device 1 is the HC3 itself**; its name is the controller name and its
  sunrise/sunset follow the virtual clock, computed on read.
  *Pinned by:* `tests/test_suncalc.py` (device-1 properties)
- **New devices land in the default room 219** (which belongs to default
  section 219), unless the seed says otherwise.
  *Pinned by:* `tests/test_api.py::test_device_created_and_removed_events`,
  `tests/test_qa.py::test_dynamic_load_from_file`

## API routing & dispatch

- **Handlers are pure**: `(SimState, ApiRequest) -> (data, status)`. Side
  effects go through `req.emit` / `req.remote` / `forward_to_proxy`; handlers
  never mutate Lua or block the pump.
- **Sim answers first; unknown ids forward** (hybrid routing). An
  offline-pinned QA (`--%%mode:offline`) never reaches the HC3 at all.
  *Pinned by:* `tests/test_hc3.py::test_offline_directive_pins_secondary_qa_to_sim`,
  `test_mode_directive_pins_secondary_qa_to_sim`,
  `test_flua_namespace_ids_never_forward`
- **`api.get('/devices')` online serves the union** of sim and HC3 devices;
  the sim wins on id clashes, so a proxy QA and its HC3 twin count once.
  *Pinned by:* `tests/test_hc3.py::test_devices_list_is_union_of_sim_and_hc3`,
  `tests/test_proxy.py::test_devices_list_has_no_proxy_doublets`
- **`api.hc3.*` bypasses the hybrid dispatch** (always the real HC3 online;
  stands in for the sim offline).
  *Pinned by:* `tests/test_hc3.py::test_api_hc3_bypasses_the_hybrid_dispatch`

## refreshStates feed & events

- **State updates are EVENTS; configuration edits are CHANGES.** Property
  changes → `DevicePropertyUpdatedEvent`; name/room edits → the `changes`
  feed. `GET /refreshStates?last=N` returns both, seq strictly increasing.
  *Pinned by:* `tests/test_api.py::test_refresh_states`
- **Device events carry the real HC3's envelope** — `type/created/
  createdMillis/sourceType/objects/data`. Global-variable events carry the
  lighter envelope (no `objects`/`sourceId`), like the captured HC3 samples.
  *Pinned by:* `test_refresh_states`, `test_global_variable_events`
- **Events are emitted only when the value actually changes** — Lua equality
  semantics (`true ~= 1`, numbers compare across int/float). An
  `updateProperty(v)` with `v` already set is silent.
  *Pinned by:* `test_refresh_states`, `test_global_variable_events`
- **Device creation/removal emit `DeviceCreatedEvent` / `DeviceRemovedEvent`**
  in the HC3's shapes: created carries `{id}`, removed carries
  `{id, deviceName, type, roomId, roomName, sectionName}`. Emitted for QA
  registration, child create/remove, and `DELETE /devices/{id}` — and
  delivered to every `RefreshStateSubscriber` through the pump.
  *Pinned by:* `test_api.py::test_device_created_and_removed_events`,
  `test_qa.py::test_device_created_and_removed_events_reach_subscribers`
- **Proxy devices never emit local refresh events** — the real HC3 owns them
  and its event comes back through the refreshStates poll; a local one would
  duplicate it. Same for actions arriving from proxy callbacks.
  *Pinned by:* `tests/test_proxy.py::test_proxy_update_property_forwarded_event_comes_from_hc3`
  (plus the created/removed no-duplicate assertions in the child tests)

## Virtual clock & timers

- **All timers schedule against the virtual clock**; the pump advances it by
  real elapsed time (`--speed` multiplies, `--instant` jumps deadline to
  deadline). `os.time()`/`_FLUA.millitime()` read the virtual clock.
  *Pinned by:* `tests/test_clock.py`, `tests/test_virtual_time.py`
- **`--%%maxhours` / `--run-for` cap the horizon**: timers beyond the
  absolute virtual deadline never fire, so instant mode stops exactly at the
  limit instead of racing past it.
  *Pinned by:* `tests/test_annotations.py::test_maxhours_annotation_stops_endless_interval`
- **A QA's timers are cancelled on restart** — the old instance's pending
  callbacks must never fire after `plugin.restart`.
  *Pinned by:* `tests/test_sleep.py::test_plugin_restart_reruns_qa`
- **Sleep defers, never drops**: while a QA sleeps, its messages queue and
  run after the sleeping callback resumes; timers due during the sleep run
  after it.
  *Pinned by:* `tests/test_sleep.py` (the whole file)

## QA boot

- **`--%%var` values are served as `quickAppVariables` on the QA's device
  before `onInit` runs** — like the HC3 creating the device with its
  `initialProperties` first. `api.get("/devices/<id>")` inside `onInit`
  already shows them, so QAs that build child devices from variable names
  (the SolarEdge Live pattern) work.
  *Pinned by:* `tests/test_modbus_mock.py::test_var_directives_seed_quick_app_variables`
- **`--%%svar` values are `--%%var` values typed `password`**: the device's
  `quickAppVariables` entry carries `type: "password"` (the HC3's web quickvar
  editor masks it with `*****`), while `getVariable`/the API still return the
  real value. A `--%%svar` wins over a same-named `--%%var`, and the
  package bake (`--tool pack`/`flua export`) keeps the `password` type, so
  the placeholder a distribution package ships stays masked on the receiving
  HC3 too.
  *Pinned by:* `tests/test_qa.py::test_svar_seeds_password_typed_variable`,
  `tests/test_tools.py::test_build_fqa_svar_bakes_password_type`
- **`--strict-tests` failures are sticky**: an unhandled callback error at
  the timer/UI/net dispatch boundaries is recorded (never cleared), and the
  final exit code becomes 1 even when a later callback calls
  `_FLUA.exit(0)` — opt-in, so the default keeps the HC3 behavior where
  callback errors only log. `--result-json` writes the verdict atomically
  (a missing file after a kill is incomplete, never a pass).
  *Pinned by:* `tests/test_dx.py::test_strict_tests_sticky_callback_failure`,
  `test_strict_tests_covers_ui_callbacks`, `test_strict_tests_covers_net_callbacks`,
  `test_result_json_statuses`
- **HC3 string extensions exist**: `string.split`, `string.starts`,
  `string.ends` behave like the HC3's.
  *Pinned by:* `tests/test_modbus_mock.py::test_string_starts_and_ends`

## Restart & state survival

- **`plugin.restart` re-runs the QA's code** (onInit again) while the device
  struct survives: `quickAppVariables` and runtime property changes carry
  over.
  *Pinned by:* `tests/test_sleep.py::test_plugin_restart_reruns_qa`
- **A QA restart revives `exited`** so the new code's timers are not refused;
  a dead QA's timer registrations are dropped.
  *Pinned by:* `tests/test_qa.py::test_exited_qa_restart_runs_timers_again`

## Graceful exit & keep-alive

- **A run ends when pending work drains** — timers, queues, in-flight
  requests/connections, and suspended QAs' remote calls all count (see
  concurrency.md). `--%%keep-alive:true` (online) and `--%%mode:proxy` hold
  the run open past idle; the HC3 poller alone never does.
  *Pinned by:* `tests/test_hc3.py::test_keep_alive_directive_keeps_engine_pending`
- **Background timers never keep the run alive** — a callback tagged with
  `_FLUA.background(fn)` still fires while the run lives, but its timers
  are excluded from the pending-work check, so the run drains when the
  real work is done (EventRunner's midnight scheduler). The tag rides the
  function, so self-rescheduling loops inherit it; a QA whose only work is
  tagged exits immediately at boot.
  *Pinned by:* `tests/test_timers.py::test_background_timers_do_not_count_as_pending`,
  `tests/test_qa.py::test_background_timers_fire_but_never_keep_the_run_alive`,
  `tests/test_qa.py::test_background_only_qa_exits_immediately`
- **Exit codes aggregate**: a failing QA fails the process; the last failing
  QA's code wins. Verdict lines go to stderr so stdout stays parseable.
  *Pinned by:* `tests/test_agent_dx.py::test_multi_qa_exit_aggregation`
- **`--ui` serves the viewer and keeps the run alive** — the server never
  counts as pending work, the session does.
  *Pinned by:* `tests/test_ui_server.py::test_ui_flag_keeps_api_alive_after_qa_drains`

## Lua bridge & runtime

- **Single-entry**: Lua is entered only from `_FLUA.dispatch(batch)`; all
  bridge messages are JSON-compatible dicts (`messages.py`). Never cross a
  Lua function reference.
- **`_PY` stays minimal** — convenience lives in Lua
  (`lua/init.lua`, `quickapp.lua`).
- **QAs are isolated**: per-QA environments, globals, and timers; a QA's
  `x = ...` never leaks into another.
  *Pinned by:* `tests/test_qa.py::test_qa_environments_are_isolated`
- **`flua-test` assertions are inert without flua** — shipped to a real HC3,
  every assertion is a no-op and `finish()` returns 0.
  *Pinned by:* `tests/test_agent_dx.py::test_flua_test_noop_without_flua_runtime`

## Compatibility surfaces (do not change silently)

- `--%%` directives, CLI flags, public Python APIs (`LuaEngine`, `Api`,
  `SimState`), and the Lua runtime APIs (`api.*`, `fibaro.*`,
  `RefreshStateSubscriber`, event shapes) are compatibility-sensitive.
- **Directive parsing**: later lines override, headers can appear anywhere,
  non-header lines are ignored, `--%%var`/`--%%property` merge per key,
  `--%%file` collects in order.
  *Pinned by:* `tests/test_config.py`, `tests/test_annotations.py`
- **The examples are living fixtures** — the test suite runs them; they must
  keep terminating unless their purpose is to run forever.
  *Pinned by:* `tests/test_sleep.py::test_example_*`, `tests/test_qa.py::test_example_*`

## Testing conventions (the suite's own contracts)

- **Never hit a real HC3.** Online/proxy tests run against local mock HC3
  servers; live suites (`test_hc3_live.py`, `test_hc3_compat.py`) are opt-in
  with `HC3_TEST=1`.
- **HOME is isolated per test** — the developer's real `~/.env` and
  `~/.flua.lua` never leak into a run (the autouse fixture in
  `tests/conftest.py`).
- **Deterministic waits, no sleeps**: assert on QA stdout (`capsys`) or mock
  request records via `wait_until`/`wait_for_output`-style helpers, not
  fixed delays.
- **Parallel by default** (`-n auto`); `--serial` for debugging. Tests that
  rewrite shared repo files must run against temp copies (the sync-skills
  test does), or they race the other workers.
