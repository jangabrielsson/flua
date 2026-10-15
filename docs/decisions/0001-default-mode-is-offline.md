# 0001 — offline is the default mode

- **Status:** active
- **Date:** 2026-10-15 (retroactive — documents long-standing behavior)

## Context

flua runs the same QA file offline (simulated HC3), online (real HC3), or in
proxy mode. A fresh checkout has no HC3 credentials, and a tool that silently
phoned a production controller by default would be dangerous — flua is
installed by people whose controller lives on their LAN.

## Decision

The default is **offline** (the simulated HC3). Online is opt-in, in two
independent ways: an explicit `--api remote` flag, or the main QA's
`--%%mode:online|proxy` directive. `--api` always wins over directives;
the first QA spec carries the mode.

## Consequences

- A bare `flua script.lua` never needs credentials and never touches the
  HC3. `cli.py::_resolve_runtime` pins this; `tests/test_hc3.py::
  test_cli_default_mode_is_offline` is the contract test.
- Credentials only matter once the run opts in; the env chain
  (`HC3_URL`/`HC3_USER`/`HC3_PASSWORD`) stays unused offline.
- The mode-comparison table in USAGE.md documents the three-way resolution.

One code comment claimed online was the default; that comment was stale and
was corrected when this decision was written down.
