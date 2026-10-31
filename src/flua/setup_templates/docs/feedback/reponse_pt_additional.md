# Response to "Additional Flua proposals: testing asynchronous and long-lived QuickApps"

Reply to `flua_additional_proposals.md` (A01–A10), for the same feedback
authors. Current release: 0.1.114.

Thank you for keeping the quality bar: synthetic-only scenarios, no
silent real-device fallbacks, positive and negative fixtures per proposal,
and the repeated "not proof of firmware parity" honesty. We reviewed all
ten against the current tree. One headline before the item-by-item: **none
of A01–A10 is a flua defect**, and you said so yourself. They are
harness-layer features, and roughly half of them can be built today on
primitives flua already ships — which shapes our response below.

## What already exists (and where to find it)

Several proposals are largely covered by existing machinery; the remaining
delta is a convenience layer, not new capability:

- **A02 (scripted transports)** — flua's own test suite scripts local mock
  HTTP/WebSocket/TCP servers for exactly these cases: delayed responses,
  disconnects, duplicate notifications, stale GETs after newer events,
  401/429 retry schedules. Any QA-side fixture can do the same with
  `net.HTTPServer`/`TCPServer`/`UDPServer`/`WebSocketServer` (in-QA
  servers) or an external loopback server. The missing piece is only a
  *declarative* scripting layer on top — real, but convenience.
- **A05 (migration fixtures)** — `--%%db` seeds a populated inventory
  (devices, rooms, scenes, variables, profiles) and `db_persist` round-trips
  it; `--tool migrate` scans existing projects. A synthetic-inventory
  builder with before/after comparison would be new glue, not new
  machinery.
- **A06 (correlated latency)** — `--trace api,ui,net,timer` already emits
  structured per-event records with virtual-clock timestamps; correlating
  them by one operation ID is the delta.
- **A07 (lifecycle resources)** — already on our list as the resource
  summary (pending timers, owned requests, subscriptions, queues); your
  generation-tagged retention diagnostics extend it.
- **A08 (seeded async scenarios)** — `flua record` / `--%%replay` seed and
  replay recorded house sessions on the virtual timeline.
- **A09 (source-vs-package differential)** — pack/unpack round-trip tests
  exist; the observation-diff harness (run both forms against identical
  fixtures, compare declared observations) is the new part.

## What we are shortlisting as small future flua additions

Two items are self-contained enough to belong in flua rather than in an
external harness:

- **A04 (write-volume diagnostics)** — a ledger of writes by QA/target/
  operation/time window, attempts vs actual changes, with test budgets.
  Diagnostic value is real and it fits the existing `--trace`/result-json
  reporting model.
- **A10 (structural UI validation)** — `--check` extended with unique
  element names per device scope, callback-target existence, selected-value
  validation and update-frequency budgets. Modest, rides the uiView
  machinery, and catches exactly the "missing button callback" class that
  bit real QAs.

## What we are parking

**A01 (slow-controller profiles)** and **A03 (restart injection)** are
genuinely new fault-injection frameworks — substantial, and in our
judgment better built as an external harness on flua's public surface
(the sim API, `plugin.restart`, mock transports) than inside the emulator.
They are filed with the rationale, not rejected: if real projects start
hitting timing/queueing bugs that only these expose, the calculus changes.

Everything is recorded in `docs/rainy_day_todos.md` with the per-item
overlap notes, so this context survives.

## One recurring theme we agree with

Your "suggested delivery approach" says to reuse existing tracing,
transports and helpers rather than a parallel framework — that is exactly
our position. flua's value is the trustworthy emulator (`--strict-tests`,
`--result-json`, deadline-ordered clocks, the pinned REST contracts);
fault injection and scenario orchestration belong one layer up, where they
can be application-shaped. We would rather add small primitives (A04, A10)
that every harness benefits from than absorb the harness itself.

As always: any of these that a real project ends up needing twice gets
promoted. Feedback with reproduced defects gets top priority, as the
previous rounds showed.

— flua maintainers
