# Optional Flua change proposals

Companion to `using_flua.md`, 31 October 2026. Written for upstream consideration.

## Status and scope

These are independently reviewable change specifications, not an applied patch
or a tested implementation. Upstream may accept, modify, defer or reject each
proposal. All new commands, options, schemas and paths below are **proposed**,
not documentation of currently available features. Implementation locations are
logical components, not verified source filenames for a particular revision.
No application-specific code, configuration or credentials are included.

The first three proposals address observed behaviour. The others improve testing,
safety and documentation; they are not claims that every related feature is absent.

## Change 01: Sticky callback failures in strict test mode

**Priority:** P0. **Target:** callback dispatcher, execution state and CLI exit handling.

Proposed invocation:

```text
flua --api local --strict-tests --run-for -3 test.lua
```

Changes:

- Add opt-in `--strict-tests`, preserving legacy exit behaviour outside this mode.
- Record every unhandled Lua callback exception in run-owned failure state.
- Cover initialization, timers, UI callbacks and transport callbacks at their
  actual dispatch boundaries. An exception caught by application code is not an
  unhandled callback error. Do not infer failure merely from a log message.
- A later successful callback or explicit exit 0 must not clear a recorded failure.
- Explicit nonzero exit remains nonzero. Expected-error tests must use an explicit
  assertion mechanism rather than resetting the failure state globally.
- Define one documented exit-code mapping for runtime errors, failed assertions,
  timeouts and CLI errors; keep it consistent with the structured result.

Illustrative control flow, not a drop-in implementation:

```text
dispatch(callback):
    try execute(callback)
    catch unhandled_lua_error:
        run.failures.append(sanitized_error)
        apply_documented_continue_or_stop_policy()

finish(requested_code):
    if strict_tests and run.failures is not empty:
        return documented_failure_code
    return requested_code
```

Acceptance tests: timer assertion fails; later callback prints success and exits 0;
final status is still failure. Repeat for UI and transport callbacks. A caught
expected error passes. Legacy mode keeps its documented existing behaviour.

## Change 02: Deliver instant-mode callbacks at their due time

**Priority:** P0. **Target:** virtual clock and scheduler.

Changes:

- Advance the clock to the earliest eligible deadline, not a later queued timer.
- Execute a callback while its due time is the current virtual time. Then
  recompute the next eligible deadline, including timers created by that callback.
- Define stable ordering for equal deadlines, for example registration sequence.
- Define when zero-delay work is dispatched; avoid recursive execution that
  bypasses queued callbacks. Bound same-time work to detect an infinite loop.
- Do not advance beyond the configured virtual deadline just to complete work.
- Specify how wall-clock I/O completion interacts with instant mode. Use a
  deterministic mock scheduler where appropriate; do not imply that real network
  latency is reproduced by advancing virtual time.

Acceptance tests: the two-timer reproduction in the report passes in instant and
realtime modes. Add nested timers, equal deadlines, cancellation, zero-delay
starvation, virtual-limit boundaries and callbacks pending across QA restart.
Ordering is deterministic under an explicitly documented scheduling policy.

Compatibility: this corrects observable timing and may expose applications that
accidentally depended on the old behaviour. Describe the change in release notes.

## Change 03: Add the missing child-deletion convenience method

**Priority:** P1. **Target:** simulated QuickApp API and child registry.

Changes:

- Implement `QuickApp:removeChildDevice(id)` using the existing simulated deletion
  operation rather than maintaining an unrelated second deletion implementation.
- First document or verify HC3 behaviour for ownership checks, return values,
  unknown IDs, repeated deletion and references to deleted children.
- Keep registry updates and any notifications consistent between method and REST
  entry points. Do not silently delete another parent's device.
- If parity cannot yet be established, list the method as unsupported explicitly;
  do not supply a successful no-op.

Acceptance tests: a synthetic parent creates and removes its child; both parent
registry and REST inventory agree. Cross-parent deletion and repeated deletion
follow the documented contract. Test handling of stale object references.

## Change 04: Explicit isolated test profiles

**Priority:** P1. **Target:** configuration resolution, transports and tool entry points.

Proposed options:

```text
--network-policy deny|loopback|allowlist
--allow-host localhost
--no-user-config
```

Changes:

- Apply policy at the supported transport boundary, including HTTP, WebSocket,
  reconnects and retries; document any routes outside that boundary.
- Deny before connection. Define DNS and redirect rules, IPv4/IPv6 handling and
  hostname resolution checks so an allowed name cannot redirect to a denied host.
- `--no-user-config` disables implicit home/project credential/config discovery;
  explicitly provided fixture configuration remains available.
- Upload, remote API and live proxy operations require separate explicit opt-in;
  a simulated HC3 mode alone must not grant it.
- Produce a sanitized policy-denial event with no authorization headers or query secrets.

Acceptance tests: loopback fixture works; LAN/external targets and disallowed
redirects fail; background retries cannot bypass the policy; inherited fake
credentials are not loaded. No test contacts a real controller or device.

Compatibility: opt-in initially. State clearly that this is supported-transport
isolation, not a security sandbox for arbitrary Lua/Python/native extensions.

## Change 05: Bounded execution and a machine-readable final result

**Priority:** P1. **Target:** test runner lifecycle and reporting.

Proposed options: `--wall-timeout 20` and `--result-json result.json`.

Proposed result example:

```json
{
  "schemaVersion": 1,
  "status": "failed",
  "exitCode": 1,
  "runtime": {"flua": "<version>", "lua": "<version>", "integerBytes": 8},
  "clockMode": "instant",
  "networkPolicy": "deny",
  "wallSeconds": 0.7,
  "virtualSeconds": 2,
  "failures": [{"kind": "callback_error", "callbackKind": "timer"}],
  "cleanupComplete": true
}
```

The values illustrate a schema, not an observed result or committed exit mapping.

Changes: independent monotonic wall-time supervision, virtual-time limit,
atomic final-result write and a documented schema. Distinguish pass, fail and
timeout; a completion marker is not sufficient. Terminate only owned execution
resources, never unrelated processes. If a native call blocks the interpreter,
supervision may need an outer process rather than another callback in that interpreter.

Acceptance tests: infinite Lua loop, blocked fixture request and ordinary success.
Final status and process exit agree. Cleanup is verified. A missing final result
after a forceful kill must be treated as incomplete, never as a pass.

## Change 06: Versioned capabilities and executable skills

**Priority:** P1. **Target:** capability metadata, documentation and CI.

Proposed command: `flua --capabilities-json`.

Changes: list API support as implemented/partial/unsupported with release/runtime
metadata. Separate simulator tests from verification on actual HC3 firmware.
Cover child lifecycle, storage, UI formats, callbacks and JSON array/null handling.

Add or consolidate skills for strict CI testing, clock semantics, isolation/mock
transports, lifecycle cleanup and export safety. Test every command example in
CI against the release. Generate bundled and repository skill copies from a
single source or check their equality. Setup should offer a merge preview and
preserve existing workspace instructions/settings unless replacement is explicit.

Acceptance tests: reported capabilities match executable probes; unsupported
features are not reported as implemented. A modified local AGENTS file survives
normal setup. Packaged guidance matches the released CLI.

## Change 07: Export preview and explicit variable handling

**Priority:** P2. **Target:** development export and configuration documentation.

Proposed option: `export ... --manifest-only`.

Changes: preview included files and variable names, value origins and whether
values would be embedded, without printing resolved secret values. Explain
configuration precedence and export resolution. Offer an explicit synthetic
fixture configuration mode and optional rejection of flagged sensitive values.
Never silently rewrite defaults or claim a heuristic scan guarantees secrecy.

Acceptance tests: a synthetic secret from external configuration is flagged
without appearing in preview/log output; export defaults and callbacks survive
round-trip checks; absent/null/false/zero/empty values remain distinguishable
where the package contract requires it.

## Change 08: Runtime and locale diagnostics

**Priority:** P2. **Target:** diagnostic output and compatibility documentation.

Changes: report Lua/Python/Lupa versions, integer size, numeric characteristics,
locale and clock mode. Explain what those values do and do not imply about HC3.
Add overflow/bit-operation/timestamp boundary fixtures and locale-sensitive UTF-8
pattern fixtures. Consider numeric32 testing only with clearly stated limitations;
do not advertise a different native runtime as an exact firmware emulation.

Acceptance tests: diagnostic output matches the executing interpreter. Boundary
tests run under each supported profile. Locale-related differences are documented
or fixed, not hidden by changing application parsing rules.

## Change 09: Optional event trace and resource inventory

**Priority:** P2. **Target:** scheduler, transport ownership and QA lifecycle.

Proposed options: `--trace-events trace.jsonl` and `--resource-summary`.

Changes: trace registration/due/delivery/cancellation, callback correlation,
generation IDs and lifecycle boundaries. Summarize owned pending timers,
requests, subscriptions and queue lengths. Bound trace volume and redact payloads,
credentials and sensitive URLs by default. A resource count is not proof that
all memory is reclaimable or equivalent to process RSS.

Acceptance tests: stopping/restarting a synthetic QA releases or fences its owned
work; late completions cannot mutate the new generation. Trace size remains
bounded and synthetic secrets do not appear in output.

## Suggested acceptance sequence

Review each change independently. First qualify failure propagation and virtual
time; then add bounded, isolated execution and API parity. Diagnostics and skills
can follow in separate changes. Use only synthetic fixtures in upstream tests.
Document rejected/deferred proposals rather than treating the entire list as one
mandatory redesign. None of these proposals requires changes to production QAs
or access to a user's controller.
