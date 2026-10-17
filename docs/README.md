# flua documentation

What lives where, so contributors can tell canonical reference from scratch
notes at a glance.

## Orientation (start here)

- **[../CONTRIBUTING.md](../CONTRIBUTING.md)** — setup, dev loop, and the
  orientation pair.
- **[../ARCHITECTURE.md](../ARCHITECTURE.md)** — components and layers.
- **[concurrency.md](concurrency.md)** — the execution model: pump, bridge
  queues, per-QA coroutines, worker threads, blocking rules, graceful exit,
  and the two race lessons.
- **[invariants.md](invariants.md)** — the behavioral contracts, each with
  the test that pins it.
- **[walkthroughs.md](walkthroughs.md)** — guided traces: QA boot,
  `fibaro.sleep`, remote API suspension, event delivery, proxy shadowing.

## Decisions

- **[decisions/](decisions/)** — ADR-lite: the *why* behind deliberate
  choices (mode default, id namespaces, proxy event rules, the pump races,
  test parallelism). Update these when a decision changes.

## Reference

- **[../USAGE.md](../USAGE.md)** — the user guide: directives, modes,
  `--%%` reference, all runtime features.
- **[../AGENTS.md](../AGENTS.md)** — working rules for AI agents (any
  framework).
- **[../CHANGELOG.md](../CHANGELOG.md)** — release notes.
- **[specs/](specs/)** — checked-in external references: `hc3-api.json`
  (the HC3 REST surface), `refreshEvents.json` (real event samples the
  emulator matches), `fibaro-sleep.md`, and HTML captures of HC3 docs.

## Tutorial (user-facing)

- **[tutorial/](tutorial/)** — the non-programmer tutorial (Sunset Lamp),
  plus its built PDF. Regenerate with `scripts/build-tutorial-pdf.sh` after
  editing chapters.

## Scratch notes (not canonical)

These live in [notes/](notes/) and capture in-progress thinking. Treat them
as dated working notes, not reference — promote anything that becomes a
rule into the reference docs above.

- `notes-agents.md` — agent-facing DX ideas (now partly realized: flua-test,
  `--log json`, AGENTS.md).
- `notes-mcp.md` — flua as an MCP server (draft design: tool surface,
  sessions, stateless transport).
- `notes-rest-parity.md` — HC3 REST parity strategy; real `/debugMessages`
  implemented, system/crash log drafted.
- `notes-distribution.md` — packaging/distribution surfaces.
- `notes-mqtt-broker.md` — MQTT broker explorations.
- `notes-select-value.md` — select-value UI semantics.
