# Rainy-day todos

Non-urgent, nice-to-have improvements — agreed as valuable but parked
until a natural moment (or a second user request). Each entry keeps the
rationale from the triage so the context survives. Remove an entry when it
ships; the date marks when it was parked.

Parked 2026-10-31, from the forum feedback triage (docs/feedback/):

## Network policy — deny/loopback gate (Change 04, simplified)

- **What**: an opt-in `--network-policy deny|loopback` (and a
  `--no-user-config` for inherited credential/config discovery) applied at
  flua's transport boundary — HTTP/WebSocket/TCP/UDP. Deny before connect.
- **What NOT to build**: the full proposal's allowlists, DNS-resolution
  checks, redirect rules, IPv4/IPv6 parity. A wrong network policy sells
  false confidence, and it is accident-prevention, not a security sandbox
  (a hostile QA runs in-process).
- **Rationale**: real value for running foreign/untrusted QAs (the pt
  report ships its own audit-hook wrapper for exactly this); the 80%
  version covers the accident risk.
- **Pinning test**: loopback fixture works; external target fails before
  connect; background retries respect the policy; no live devices.

## Export preview — `--manifest-only` (Change 07)

- **What**: `flua export ... --manifest-only` — the files and variable
  names the package would ship, value origins (expression/config file),
  and whether values would be embedded — without printing resolved secret
  values.
- **Rationale**: export-safety glance for the distribution workflow; low
  effort. flua already has the placeholder/bake machinery, so this is
  presentation, not new resolution logic.

## Resource summary (Change 09, the small half)

- **What**: `--resource-summary` — pending timers, owned HTTP requests,
  subscriptions, queue lengths, before/after stop or restart. Leak and
  lifecycle debugging.
- **What NOT to build**: the full event-trace file (registration/due/
  delivery/cancellation correlation, generation ids) — `--trace
  api,ui,net,timer` + syslog/timeline already cover most of it.
- **Rationale**: small, real debugging value; the full trace would be
  re-doing the existing trace channel at medium cost.

## Documentation asks from the pt report

- **Windows/locale guide**: Lua byte-pattern classification, encoding,
  interpreter/locale details in diagnostic output; the guarded-name probe
  passes but the unguarded case is not established.
- **UI/export fidelity guide**: what simulated UI events and string values
  can and cannot establish about real HC3/browser/mobile rendering; legacy
  vs newer UI export; select defaults.
- **Lifecycle/observability guide** (or skill): pending resources and
  late-callback fencing across stop/restart — likely folds into the
  resource summary above.

## Batch C leftovers already rejected (do not resurrect without new evidence)

- Full network allowlist/DNS/redirect machinery (Change 04 full).
- Second, richer event-trace format (Change 09 full) — the existing
  `--trace` channel wins on maintenance cost.

## From the pt additional proposals (parked 2026-10-31, A01–A10)

The author framed these as optional, non-defect proposals. Honest verdict:
they are **harness-layer features**, and most of them are better built on
top of flua's primitives than inside the emulator. flua already offers the
foundations: scripted transports via local mock servers (the tests do this
everywhere), `--strict-tests` + `--result-json`, `--%%replay`/`flua record`,
`--%%db` seeding, the migrate tool, `--check`, and `--trace
api,ui,net,timer`. None of A01–A10 blocks real work.

- **A01 slow-controller/constrained-dispatch profiles** — synthetic REST
  latency/queue models. Valuable for exposing timing bugs, but a
  fault-injection framework of its own; park until someone asks twice.
- **A02 scripted transport completion** — partially available today
  (local mock HTTP/WS/TCP servers can already script delays, disconnects
  and duplicate notifications; the repo's tests do this). The missing
  piece is a reusable, declarative scripting layer — park.
- **A03 restart injection** — `plugin.restart` and the restart tests exist;
  the checkpoint/sequence-number injection harness does not. Park.
- **A04 write-volume diagnostics** — the only small, self-contained item:
  a write counter (by QA/target/operation, attempts vs changes). Good
  candidate for a small implementation; shortlist it.
- **A05 migration fixtures** — overlaps `--%%db` seeding + the migrate
  tool; the synthetic-inventory builder + before/after comparison is new.
  Park.
- **A06 correlated latency** — overlaps `--trace timer,net`; the
  stage-by-stage operation-ID correlation is new. Park.
- **A07 lifecycle resources** — already filed above (resource summary,
  Change 09-half). Merged, no new entry.
- **A08 seeded async scenarios** — overlaps `--%%replay`/`flua record`.
  Park.
- **A09 source-vs-package differential testing** — overlaps pack/unpack
  round-trip tests; the observation-diff harness is new. Park.
- **A10 structural UI validation** — overlaps `--check` and the uiView
  machinery; the validation rules (unique names, callback targets, update
  budgets) are new and modest — shortlist alongside A04.

## Extensibility: stabilize the embedding surface + three edge hooks (parked 2026-10-31)

From the "Python plugin mode with SDK?" discussion. Verdict: build targeted
edge hooks, not a general plugin framework — flua's moat is trustworthiness,
and every plugin boundary risks it.

- **Stabilize and document the embedding surface** — `LuaEngine` (constructor,
  `api.dispatch`, state access, the bridge rules) is already the de-facto
  SDK (the MCP server, the tools and external harnesses all drive it); the
  pain point in feedback is that it is *internal* and may change. Document
  it, name what is stable, keep the rest internal.
- **`--tool` plugin directory** — auto-discover tool modules from a user
  directory alongside the in-package registry (the registry already
  auto-discovers; pointing it at an extra path is trivial).
- **Custom REST route registration on the sim `Api`** — e.g.
  `api.add_route(method, pattern, handler)` for vendor-specific endpoints;
  the natural server-side home for scripted transports.
- **Lua `require` path/preload injection** — a plugin dir on the QA's
  `package.path`/preload registry, so shared Lua libraries come from a
  plugin instead of per-project copies.
- **Deferred until someone needs it twice:** transport/server kind
  registration (new `net.*Server` protocols — the engine's server dispatch
  is hardcoded).
- **Refused:** a full plugin lifecycle (sandboxing/loading/versioning —
  no security story exists in-process, and it is permanent API surface);
  hooks into the pump/scheduler/clock (where the invariants live).
