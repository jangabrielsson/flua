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
