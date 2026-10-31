# Using Flua to test and debug Fibaro QuickApps

Experience report for the Flua maintainer, prepared 31 October 2026.

## Summary

Flua is useful as a fast, local feedback loop for QuickApp development. It lets us
check Lua code, exercise a simulated QA lifecycle, run existing regression tests,
test HTTP handling against a local fixture server, and inspect development FQA
exports without repeatedly installing code on a physical HC3.

The most important improvement would be making automated test outcomes reliable:
an unhandled timer callback error should fail the process, and accelerated time
should preserve what each callback observes. Both currently require precautions
in our external runner. Better isolation controls and an explicit HC3 compatibility
matrix would also substantially increase confidence and reduce setup effort.

This report describes our actual tests, not a complete review of Flua. We did not
qualify interactive breakpoint debugging, live proxy mode, or physical device
control in this pilot. Suggestions below are requests, not claims that every
related feature is absent from the current project.

## Environment and evidence

Latest run:

| Item | Value |
| --- | --- |
| Flua package | `fibaro-flua==0.1.110` |
| Python | 3.12.10 on Windows |
| Lupa | 2.6 |
| Reported Lua runtime | 5.4 |
| Lua integer width observed | 8 bytes |
| Locale used by our runner | C |
| Test date | 31 October 2026 |
| Result | 29 of 30 checks passed |
| Dependency consistency | `pip check` passed |
| Real controller access | None |

The suite consists of 13 simulator/tooling checks and 17 application-level
regression fixtures. All 17 application-level fixtures passed. These fixtures
contain their own mocks/stubs; that is useful regression coverage but is **not**
proof of complete native API compatibility or physical-device behaviour.
Application names, implementations and deployment details are intentionally omitted.

We also have earlier results for 0.1.23, 0.1.33 and 0.1.93. The current 0.1.110
run still shows the instant-mode timer issue and zero exit status after an
unhandled callback error. A variable-default export problem observed in an older
version is no longer reproduced by our current probe.

The local evidence includes versioned outcomes, captured output, execution times,
input hashes, a bounded runner, an isolation wrapper and synthetic probes.
Private workspace paths and application-specific evidence are not included.
Reproduction examples below are self-contained and require no private data.
Concrete optional changes are specified separately in
[using_flua_proposed_changes.md](using_flua_proposed_changes.md).

## What worked well

### Fast feedback without a controller deployment

The current simple checks and application-level fixtures typically completed in
about 0.6-1.7 seconds each; the realtime timer probe took about 2.7 seconds.
That is a useful development loop for checking a change before any live test.
`--check`, short QA fixtures and ordinary Lua assertions are easy to combine.

### Reuse of existing regression tests

Existing Lua fixtures could execute inside the Flua process rather than
needing to be rewritten for another framework. Their coverage includes configuration,
capability mapping, false/zero preservation, command confirmation, stale callback
fencing, authentication handling, bounded queues, UI contracts and lifecycle
cleanup. Much of that behaviour is tested with project-provided mocks, so the
main benefit here is convenient execution and regression feedback.

### Useful simulator integration surface

Our small integration fixture passed checks around parent/child behaviour,
properties, variables, storage and simulated UI callbacks. The local REST child
deletion route worked in the pilot even though the corresponding convenience
method was absent in the separate capability probe.

### HTTP tests without contacting real devices

A separate loopback HTTP server let us exercise 200, 401 and 429 responses. This
is more representative than making every HTTP callback return synchronously.
It also allows deliberately invalid responses without touching production.

### Accelerated scenarios and development exports

A virtual-day scenario completed in roughly one second. This is useful for
scheduled behaviour, provided clock-ordering limitations are respected; it is
not evidence of a real 24-hour memory or stability test.

Development export/unpack passed. Our current metadata check preserved the
`Language=en` QA variable and a button callback. This is a narrow round-trip
check, not complete FQA fidelity or permission to replace our release tooling.

### Discoverable guidance

The upstream skills covering QA APIs, patterns, testing, setup and REST safety
are valuable starting points. The test helper approach and structured logging
are promising for both human and agent-driven workflows. Keeping that guidance
next to the implementation makes it easier to discover than scattered examples.

## Reproduced issues

### 1. Unhandled timer errors can return exit code zero

Minimal fixture:

```lua
--%%mode:offline
function QuickApp:onInit()
  setTimeout(function()
    error("EXPECTED_CALLBACK_FAILURE")
  end, 10)
end
```

Run with the equivalent of:

```text
flua --api local --color never --instant --run-for -1 negative.lua
```

In our guarded 0.1.110 run, the callback error and `stack traceback:` were printed,
but the native process returned **0**. Our negative-control test passed because
our wrapper expected and detected the error, not because Flua returned failure.

**Impact:** CI that checks only the process status can report broken code as
successful. A later success marker does not solve this either: another callback
can print it after an earlier callback has failed.

**Suggested improvement:** a documented strict test mode with a sticky failure
state and nonzero final status for unhandled callback errors, including timer,
UI and network callbacks. A later successful callback or `_FLUA.exit(0)` should
not silently clear that state. Also provide a machine-readable final summary.

### 2. Instant-mode callbacks can observe a later timer's time

Our actual regression fixture:

```lua
--%%mode:offline
function QuickApp:onInit()
  local start = os.time()
  setTimeout(function()
    assert(os.time() - start == 1, "FIRST_TIMER_TIME_JUMPED")
  end, 1000)
  setTimeout(function()
    assert(os.time() - start == 2)
    print("TIMER_TEST_COMPLETE")
    _FLUA.exit(0)
  end, 2000)
end
```

With `--instant --run-for -3`, the first assertion failed. The second callback
still printed the completion marker and the process returned 0. With the same
fixture in realtime mode, omitting `--instant`, the test passed.

This establishes an observable clock problem; it does not by itself establish
that the callbacks were executed in reverse order or identify the internal cause.

**Impact:** timeout, debounce, retry, freshness and expiry tests may give
misleading results under accelerated time.

**Suggested improvement:** advance the virtual clock to the next due callback,
deliver eligible work with documented ordering, then advance again. Document
ordering for equal deadlines, nested timers, zero-delay work and asynchronous
completions. Add regressions for cancellation and restarting a QA with pending
callbacks as well.

### 3. Child deletion API parity is incomplete in our probe

On 0.1.110, `type(self.removeChildDevice)` printed `nil`. The simulated REST
deletion route worked in the integration pilot.

**Impact:** code using an HC3 convenience method may fail even when the underlying
simulated operation exists. Adding emulator-specific fallbacks to production QA
code would conceal the compatibility gap rather than fix it.

**Suggested improvement:** implement the method with documented semantics, or
explicitly list it as unsupported in a versioned capability table. Include child
object/reference behaviour after removal, not just removal from the inventory.

## Safety and reproducibility improvements

### Offline should have an explicit network policy

The startup banner correctly says `sim HC3, real network`. Simulating HC3 is not
the same as preventing a QA from sending requests to real vendor devices.

We added an external Python audit-hook guard that blocks non-loopback socket
access and DNS, rejects remote/tool invocation for this pilot, and disables
inherited secret/config lookup. This is accident prevention, not a hostile-code
sandbox, and our wrapper uses internal Flua APIs that may change.

Useful first-class options would be:

- Network disabled, loopback-only, and explicit host allowlist profiles.
- No inherited home/project configuration or secrets for reproducible tests.
- Separate, explicit authorization for upload, proxy and other live operations.
- A clear error when a test attempts an unexpected external request.

These should protect both direct requests and background reconnect/retry paths.

### Bound both virtual time and wall time

We use `--run-for` plus an independent wall-clock timeout. On Windows our runner
also has to terminate only the process tree it started if that timeout expires.
Virtual limits alone cannot protect against a blocked native call or runaway
execution that stops advancing simulated time.

A supported bounded test command could combine those limits, guaranteed cleanup,
failure status and result export without every user writing a wrapper.

### Make export behaviour around secrets explicit

Configuration outside the Lua source is not automatically outside the exported
FQA. Resolved variable values can become package defaults. We use synthetic
configuration and inspect exports rather than assuming external secrets stay out.

A documented export policy, dry-run manifest and optional fail-on-sensitive-value
check would help. Do not silently replace valid user defaults or claim that a
heuristic secret scan guarantees a safe package.

## Missing information and skills that would help

1. **A versioned HC3 compatibility matrix.** Distinguish implemented, partial,
   unsupported and verified-against-hardware APIs. Include callbacks, storage,
   child lifecycle, JSON null/arrays, UI formats and errors, not just method names.
2. **An authoritative scheduling contract.** Explain virtual versus wall time,
   `os.time`, equal-deadline ordering, asynchronous UI dispatch and HTTP completion.
   Include executable examples and tests for the promised behaviour.
3. **A CI/agent testing skill.** Show negative controls, sticky failures,
   completion markers, bounded execution and structured results. Explicitly warn
   that exit 0 alone is not sufficient with the currently observed behaviour.
4. **An isolation and mock-transport skill.** Provide HTTP/WebSocket fixtures for
   latency, disconnects, late callbacks, 401/429 and retries, with no fallback to
   a real endpoint. Distinguish mocks supplied by the QA project from native
   simulator coverage.
5. **A numeric-runtime guide.** Our runtime reports 8-byte integers; that does not
   qualify HC3 numeric behaviour. Explain supported profiles and limitations for
   integer overflow, floating-point timestamps and bit operations. A numeric32
   test profile would be useful where technically feasible; it is not necessarily
   a faithful emulation of every controller firmware.
6. **A Windows/locale guide.** We pin C locale after earlier UTF-8 name/pattern
   problems. The current guarded name probe passes; we have not established that
   unguarded 0.1.110 still reproduces the original issue. Document Lua byte-pattern
   classification, encoding and interpreter/locale details in diagnostic output.
7. **A UI/export fidelity guide.** Explain simulated UI events, string values,
   legacy versus newer UI export, select defaults and what the local preview
   cannot establish about actual HC3/browser/mobile rendering.
8. **Safe setup and skill maintenance.** Keep root guidance and packaged skill
   copies synchronized. Clearly separate old examples from current commands.
   Setup should preserve existing AGENTS files, tasks, settings and local work;
   offer a merge preview rather than requiring force overwrite.
9. **A lifecycle and observability skill.** Show pending timers, owned HTTP
   requests, subscriptions, queue lengths and references before/after stop or
   restart. This would help investigate leaks and late callbacks more directly.

Some of this may already exist in pieces. The improvement is a tested, coherent
entry point that says which guarantees apply to the installed release.

## Debugging experience and limitations

Our strongest experience is assertion-driven debugging: small reproductions,
captured logs, comparison of realtime and accelerated execution, and inspection
of state after simulated actions. That workflow is productive.

We have not measured the quality of breakpoint stepping, variable inspection,
debugger attachment, or live proxy debugging in this pilot. We therefore cannot
fairly label those features good, broken or missing.

For deeper asynchronous debugging, an optional event trace would be valuable:
timer scheduled/due/delivered/cancelled times, request and callback correlation,
QA generation/restart identifiers and callback failures. Payloads and credentials
should be redacted by default. A documented run/inspect/step interface could
then help tooling without requiring access to internal Python classes.

## Suggested upstream priorities

| Priority | Work | Acceptance test |
| --- | --- | --- |
| P0 | Reliable callback failure status | Deliberate timer error ends nonzero, even if a later callback exits 0 |
| P0 | Correct accelerated clock semantics | Both callbacks in the timer example observe their own deadlines |
| P1 | First-class isolated test execution | External requests are denied; loopback fixtures work; no inherited secrets |
| P1 | Capability matrix and child deletion parity | Unsupported APIs are explicit; implemented methods have lifecycle tests |
| P1 | Structured test results and bounded execution | CI needs no traceback regex; wall and virtual limits are independently enforced |
| P2 | Runtime profiles, event tracing and lifecycle diagnostics | Numeric limitations and pending resources are inspectable |
| P2 | Consolidated executable skills and export guidance | Examples are tested against the release and preserve existing workspace files |

## How we would use Flua going forward

Keep Flua as a fast layer between pure unit tests and physical-controller tests:

1. Static checks and pure Lua regression tests.
2. Isolated Flua integration tests with explicit inputs and mocked transports.
3. Realtime tests for ordering-sensitive cases until instant mode is qualified.
4. Independent numeric32 checks where required.
5. Physical HC3 installation, upgrade, UI, event-delivery and stability checks.

Flua should not have to reproduce every physical device to be valuable. Clear
boundaries, reliable failures and deterministic scheduling would make it much
easier to trust precisely the parts it does simulate.

Our overall assessment is positive: it already saves development time. The
largest remaining cost is not writing QA tests; it is ensuring that a green
simulator run really means the tests ran correctly and failed when they should.
