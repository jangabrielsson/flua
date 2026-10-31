# Additional Flua proposals: testing asynchronous and long-lived QuickApps

Prepared for the Flua maintainer, 31 October 2026.

## Scope

These are optional, independently reviewable proposals, not newly reproduced
Flua defects or claims that the related functionality is entirely absent.
Accept, adapt, defer or reject each proposal separately. Reuse existing tracing,
transport fixtures and test helpers rather than creating a parallel framework.

All examples are synthetic. They require no production application, private
configuration, controller export, credentials or physical device. No proposed
helper should silently fall back to a real controller or network endpoint.

The scenarios below are specifications, not executed tests or implemented APIs.
The illustrative configuration is not current Flua syntax. Keep application
correctness assertions separate from the simulator's own acceptance criteria:
a test should detect a deliberately incorrect application, not make it correct
by silently repairing its behaviour.

## Priority overview

| ID | Priority | Proposal |
| --- | --- | --- |
| A01 | P1 | Slow-controller and constrained-dispatch profiles |
| A02 | P1 | Scripted transport completion and ambiguous outcomes |
| A03 | P1 | Restart injection and persistence boundaries |
| A04 | P1 | Write-volume and redundant-update diagnostics |
| A05 | P1 | Existing-installation migration fixtures |
| A06 | P2 | Correlated, stage-by-stage latency measurements |
| A07 | P2 | Lifecycle resource and retention diagnostics |
| A08 | P2 | Seeded asynchronous scenarios and replay |
| A09 | P2 | Source-versus-package differential testing |
| A10 | P2 | Structural UI validation and update budgets |

## A01: Slow-controller and constrained-dispatch profiles

**Goal:** expose timing and queueing problems that disappear on a fast development
machine. Model explicit constraints, not an unverified claim to reproduce HC3 CPU.

### Proposed changes

- Named synthetic profiles with configurable simulated HC3 REST latency,
  completion throughput, queue capacity and dispatch delay.
- Separate controller API latency from vendor transport latency and Lua execution
  cost. Do not confuse delayed completion with a blocking Lua callback.
- Expose queue depth, enqueue/delivery timestamps and the policy used when full.
- Make overload visible; never silently discard work without a documented event.
- Support virtual-time execution where deterministic and bounded realtime tests
  for actual event-loop interaction.

### Concrete scenario

A synthetic application maintains 24 children. Background work enqueues 48
low-priority updates. A button event arrives while that queue is occupied.
The fixture configures 40 ms completion latency, eight completions per virtual
second and a queue capacity of 64. An application with a priority queue should
dispatch the button's command before its remaining background work.

### Acceptance tests

1. Recorded service times, queue depth and completion rate match the configured
   synthetic profile within a declared scheduling tolerance.
2. Input delivery remains observable while background requests are outstanding.
3. A correctly prioritized fixture meets its declared latency budget; a deliberately
   FIFO-only negative fixture violates that budget and fails the assertion.
4. Exceeding capacity produces the documented overload result; request accounting
   proves there was no invisible loss or duplicate completion.
5. The default profile retains existing behaviour. Profiles are labelled synthetic,
   not measurements of a particular controller model or firmware.

## A02: Scripted transport completion and ambiguous outcomes

**Goal:** test stale responses, disconnects and uncertain command execution without
real hardware. Extend existing mock transports if possible.

### Proposed changes

- Script requests by method, endpoint and synthetic operation ID.
- Control acceptance, response delivery, delay, disconnect and duplicate notification
  independently. A connection failure does not necessarily mean a command was rejected.
- Keep a request ledger and a separate synthetic remote-state ledger.
- Fail unmatched requests instead of forwarding them to a real endpoint.
- Cover HTTP and event transports; define the clock used by each fixture.

Illustrative scenario, not a proposed stable schema:

```yaml
steps:
  - accept: {id: old_read, method: GET, path: /state}
    snapshot: {value: false}
    deliver_at_ms: 1500
  - accept: {id: command, method: POST, path: /state, body: {value: true}}
    apply_at_ms: 100
    response: disconnect_after_apply
  - emit_at_ms: 200
    event: {value: true, sequence: 12}
```

### Acceptance tests

1. The older GET returns its captured `false` snapshot after the newer event.
   A correctly fenced application retains the newer confirmed `true` state.
2. The POST is applied exactly once despite its missing response. Assert against
   both ledgers; a negative fixture that retries the write is detected.
3. Duplicate notifications do not duplicate application side effects; two distinct
   rapid notifications remain distinguishable and are not accidentally merged.
4. A scripted read retry after 401/429 follows the fixture's schedule without
   requiring or permitting an automatic write replay.
5. An unexpected request fails locally and records a sanitized mismatch.

## A03: Restart injection and persistence boundaries

**Goal:** verify recovery in the middle of an operation without treating all Lua
memory as persistent or replaying physical commands automatically.

### Proposed changes

- Inject a simulated QA restart at named checkpoints or event sequence numbers.
- Preserve only explicitly persisted state; discard the old instance's Lua globals.
- Tag owned callbacks and timers with an instance generation and expose late
  completions for testing. Document whether the engine drops or delivers them.
- Distinguish QA restart from complete simulator restart and controller reboot.
  Do not claim all three have the same persistence semantics.
- Keep external fixture state separate from application state.

### Concrete scenario

A synthetic command journal records intent. The remote fixture accepts a command,
but the response is delayed. Restart the QA before confirmation, then deliver the
old response. The replacement instance reconciles remote state through a read.

### Acceptance tests

1. Persisted intent survives; an unpersisted local variable does not.
2. The old generation's completion cannot mutate the new instance's state.
3. The fixture records exactly one original write. Recovery reads do not cause
   an unconditional resend of an uncertain command.
4. Interruptions before intent persistence, after persistence and after confirmation
   produce separately asserted outcomes.
5. Repeated restart tests leave no growing population of old timers/subscriptions.
6. A deliberately unfenced negative fixture fails, demonstrating that the harness
   is not simply suppressing every event needed to expose the bug.

## A04: Write-volume and redundant-update diagnostics

**Goal:** identify unnecessary controller traffic, history generation and UI work.
This is observation, not a request to change application semantics automatically.

### Proposed changes

- Count writes by QA, target, operation and time window: variable updates,
  property updates, UI updates, storage writes and action invocations.
- Optionally flag equal-value writes using operation-specific comparison rules.
- Distinguish state-setting writes from meaningful repeated events/actions;
  never deduplicate event delivery or actuator commands automatically.
- Track attempts separately from successful changes and expose configurable
  test budgets. Do not print secrets or whole request bodies by default.

### Concrete scenario

Feed 1,000 identical telemetry samples into a synthetic sensor fixture, followed
by one genuine value change and two distinct button presses with the same value.

### Acceptance tests

1. The ledger distinguishes all attempted writes from actual value changes.
2. An application designed to publish changes only performs one initialization
   update and one changed-value update, subject to its explicitly stated contract.
3. Both button presses remain separate observable events.
4. Repeated attempts to create an existing variable are visible as attempts, even
   when the simulated controller rejects them.
5. A deliberately unconditional-update fixture exceeds its budget and fails.
6. These counters are not presented as measurements of actual controller database
   growth, CPU load or flash wear.

## A05: Existing-installation migration fixtures

**Goal:** qualify an update against a populated installation, not only a clean boot.

### Proposed changes

- Synthetic inventory builder with stable parent/child IDs, custom names, rooms,
  interfaces, typed properties, variables and persisted storage.
- Snapshot and compare before/after migration using explicit allowlisted changes.
- Model write errors and partial migration progress; make restart/resume repeatable.
- Preserve unknown configuration fields unless the migration explicitly removes
  them under its declared contract.

### Concrete scenario

Seed a parent and six children. Include custom names and rooms, an unknown
variable, `false`, zero, empty strings and synthetic connection settings.
Run a version migration that adds one variable and updates one UI definition.
Repeat it, then inject a write failure halfway through a fresh run.

### Acceptance tests

1. IDs, bindings, custom names, rooms and synthetic connection settings remain
   unchanged unless listed as intended changes.
2. Unknown variables and metadata survive read-modify-write operations.
3. False, zero, missing and empty values are not silently conflated.
4. Re-running the migration is idempotent: no duplicate children or repeated
   creation of already existing variables.
5. Failure does not produce a successful-migration marker. Resume completes the
   declared changes without deleting unrelated state.
6. Compare behaviour with relevant controller contracts before claiming firmware
   parity; a simulator fixture alone cannot establish that parity.

## A06: Correlated latency measurements

**Goal:** show where delay occurs instead of reporting one ambiguous duration.

### Proposed changes

- Correlate source event, enqueue, dispatch, transport response, state confirmation
  and UI publication with one operation ID.
- Record wall/virtual clock domains, clock resolution and generation ID.
- Keep optimistic UI publication separate from confirmed remote state.
- Support per-stage assertions and percentiles for repeated synthetic operations.

### Concrete scenario

A fixture schedules input at t=0 ms, dispatch at t=100 ms, response at t=300 ms,
confirmation at t=450 ms and final UI publication at t=500 ms, all in one virtual
clock domain. A second variant publishes optimistic UI before confirmation.

### Acceptance tests

1. Reported input-to-dispatch, response, confirmation and final UI durations agree
   with the synthetic schedule within documented resolution.
2. Optimistic UI is not labelled confirmation or physical completion.
3. Missing confirmation is reported as incomplete/timeout, not zero latency.
4. Wall and virtual timestamps are never subtracted as though they shared a clock.
5. A run with a deliberately delayed background queue attributes the added delay
   to queueing rather than transport.
6. Realtime measurements use a monotonic clock and declared tolerances; do not
   describe `os.time()*1000` as millisecond-resolution instrumentation.

## A07: Lifecycle resource and retention diagnostics

**Goal:** make retained timers, callbacks, subscriptions and buffers inspectable.
Build on the earlier resource-summary proposal rather than introducing a second
independent ownership system.

### Proposed changes

- Record resource owner, generation, allocation/completion and cancellation status.
- Summarize pending requests, timers, listeners, queues and bounded payload caches.
- Where practical, show diagnostic retention paths maintained by the simulator;
  do not promise full cross-language heap analysis.
- Separate Lua heap, Python allocation data and process RSS. Compare equivalent
  idle checkpoints, not arbitrary samples during active work.

### Concrete scenario

Run 100 start/stop cycles of a synthetic instance with timers, one subscription,
delayed local requests and a bounded cache. Include a variant intentionally leaving
one listener registered per cycle.

### Acceptance tests

1. The correctly cleaned fixture returns to its declared baseline of owned active
   resources after each cycle and does not retain earlier generations' payloads
   through simulator-owned references.
2. The intentionally leaked listener is attributed to its owner/generation.
3. A late request completion cannot revive stopped application work.
4. Diagnostic tracing is itself bounded and does not become the apparent leak.
5. Memory trend assertions use a documented warm-up and tolerance; a single RSS
   increase or a forced GC is not claimed to prove a leak or its absence.

## A08: Seeded asynchronous scenarios and replay

**Goal:** reproduce rare interleavings without long manual trial and error.

### Proposed changes

- Generate bounded event schedules from a fixed seed and versioned generator.
- Include disconnect/reconnect, 401/429, delayed reads, rapid input events and restarts.
- Save the seed, profile, runtime versions and sanitized event schedule on failure.
- Replay an explicit recorded schedule independently of later generator changes.
- Optionally minimize a failing schedule while retaining the failing assertion.

### Concrete scenario

Generate 10,000 events over seven virtual days. Assert bounded queues, distinct
button-event preservation, generation fencing and no duplicate uncertain writes.
Run a smaller deliberate negative fixture with a stale-response bug.

### Acceptance tests

1. The same seed and generator version produce the same scheduled input sequence.
2. Replaying a saved schedule reproduces the failure in the supported deterministic
   environment, or explicitly identifies an unsupported source of nondeterminism.
3. A reduced reproduction still fails for the same checked invariant.
4. Work and trace sizes remain bounded; the suite has an independent wall limit.
5. Seven simulated days are labelled as virtual coverage, never as a real seven-day
   stability, hardware or memory qualification.

## A09: Source-versus-package differential testing

**Goal:** detect behavioural changes introduced by packaging/minification without
requiring Flua to implement or understand every packaging tool.

### Proposed changes

- Run a source form and an unpacked development artifact against the same
  synthetic inputs, runtime profile and fixture state.
- Compare observable actions, state transitions, callback bindings and metadata.
- Normalize only explicitly allowed nondeterminism, such as generated run IDs.
- Record source/artifact hashes and the normalization policy.
- Allow adapters for packaging-specific source maps or entry points without
  bypassing integrity controls or silently modifying the tested artifact.

### Concrete scenario

Package a synthetic multi-file application with one child, one button callback,
one variable default and one local transport request. Test an unchanged package
and a deliberately broken package with a renamed callback.

### Acceptance tests

1. The valid package and source produce equivalent declared observations.
2. The broken callback binding is detected and attributed to the artifact form.
3. Defaults, file inclusion/order where significant, and callback metadata are
   checked separately from runtime actions.
4. Normalization cannot hide missing events, reordered commands or changed values.
5. Inputs are synthetic and no resolved credentials enter the exported artifact.
6. Passing this comparison is not presented as signing, licensing, firmware or
   public-release qualification.

## A10: Structural UI checks and publication budgets

**Goal:** find invalid callback bindings and excessive UI updates before deployment.

### Proposed changes

- Validate unique element names within the relevant device scope, callback targets,
  selectable values and expected event-value shapes.
- Identify updates to nonexistent elements and distinguish hidden from missing UI.
- Count update frequency and payload volume per element without automatically
  suppressing meaningful repeated events.
- Optionally snapshot normalized UI structures for supported export formats.

### Concrete scenario

A synthetic UI contains a button, a single select and a label. Variants introduce
a missing button callback, duplicate element name and invalid selected value.
One telemetry stream repeats the same label text 1,000 times; another changes it.

### Acceptance tests

1. Each invalid variant reports the exact device/element and validation rule.
2. Identical element names on different children are permitted where the contract
   scopes names per device; no false global-uniqueness rule is imposed.
3. Event values preserve the documented string/list wrapping and asynchronous
   delivery semantics, including empty selections.
4. A change-only UI fixture stays within its declared update budget; an intentionally
   unconditional renderer exceeds it and fails.
5. Supported export round trips preserve callback bindings and selected defaults,
   or report a documented format limitation instead of silently claiming fidelity.
6. Structural validation is explicitly not proof of actual browser/mobile layout,
   text clipping, scrolling or physical controller rendering.

## Suggested delivery approach

Start with small extensions to existing fixture and trace APIs. A01-A04 offer
the strongest immediate value for asynchronous failures and excessive workload;
A05 adds migration safety. The remaining items can build on those foundations.

For each accepted proposal, publish one positive fixture, one deliberately faulty
negative fixture and the exact guarantees being tested. Keep strict-mode failure
and structured-result handling consistent across all helpers. Preserve independent
wall-time supervision and clear incomplete-run reporting.

No feature should require a private application, automatic controller access,
production data or physical output changes to demonstrate its usefulness.
