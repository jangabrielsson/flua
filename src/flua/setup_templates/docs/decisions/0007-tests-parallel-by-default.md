# 0007 — tests run parallel by default, with a serial hatch and a slow-marker gate

- **Status:** active
- **Date:** 2026-10-15

## Context

The suite had grown to 433 tests at ~2 minutes serial. The tests are
independent (ephemeral localhost ports, per-test HOME isolation, tmp_path),
so the time was pure CPU, not contention.

## Decision

- **Parallel by default**: `pytest-xdist` with `-n auto` in addopts —
  ~19 s on 8 cores, ~35 s on the CI's 2-core runners.
- **Serial hatch**: `--serial` (implemented as a `tryfirst`
  `pytest_cmdline_main` hook in the root `conftest.py` — the only hook
  point early enough to override xdist's `-n auto` resolution); plain
  `-n 0` also works.
- **Fast gate**: tests that deliberately spend wall-clock time (real
  sleeps, protocol settles, socket timeouts) carry the `slow` marker;
  `-m "not slow"` runs the pure-logic core in ~6 s.
- **Mock teardown**: threaded mock servers start `serve_forever` with
  `poll_interval=0.01` (Python 3.14's default 0.5 s would tax every
  fixture).
- **No shared-tree writes**: the sync-skills test runs against temp copies
  (`SKILLS_SRC`/`SKILLS_DEST`), so workers never rewrite the repo while
  others read it.

## Consequences

- Trade-off: parallelism makes timing bugs visible (it surfaced 0005,
  0006, and two latent teardown races) — that is treated as a feature.
- Pre-existing format drift in some test files is left untouched; only new
  hunks are kept format-clean.
