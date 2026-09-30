# Contributing to flua

Thanks for your interest! flua is an open project — pull requests are
welcome.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"     # pytest + ruff
```

Requires Python 3.11+; `lupa` is the only runtime dependency.

## Development loop

```bash
.venv/bin/pytest tests/ -q            # full suite (live-HC3 tests are skipped)
.venv/bin/pytest tests/test_qa.py -q  # one file
.venv/bin/ruff check src/ tests/      # lint
.venv/bin/ruff format src/ tests/     # format (line length 100)
```

Run one test, test class, or test function with pytest's normal selectors:

```bash
.venv/bin/pytest tests/test_qa.py::test_name -q
.venv/bin/pytest tests/test_qa.py -k timer -q
```

Tests run against local mock servers, never a real HC3. The opt-in live
suites (`HC3_TEST=1 pytest tests/test_hc3_live.py`) need your own controller
credentials and touch only their own test QA.

Some tests bind localhost sockets. If tests fail in a restricted sandbox,
rerun them in an environment that permits local socket binds. Prefer existing
`wait_until`/`wait_for_output` helpers over sleeps so tests remain deterministic.

## Making a change

1. Open an issue or discuss the change first when it is not a small fix.
2. Keep changes focused: one concern per PR, behavior and tests together.
3. Add a test for new behavior — the suite is the contract. New tests follow
   the existing patterns (mock HC3 servers, `wait_until` helpers, stdout
   assertions).
4. Update the docs: user-facing behavior in `USAGE.md`, internals in
   `ARCHITECTURE.md`, new directives in the directive table.
5. Run `ruff check` and the full suite before pushing.

For larger changes, also run `ruff format --check src/ tests/` and inspect the
complete diff with `git diff --check`.

## Code style

- PEP 8 via ruff (line length 100), type hints where they help.
- API handlers are pure functions over `SimState`; side effects go through
  `req.emit`/`req.remote`.
- Everything crossing the Lua↔Python bridge is a JSON-compatible message —
  never a Lua function reference.
- Keep `_PY` (the bridge surface) minimal; end-user convenience lives in Lua.
- `dev/` is scratch; do not commit probes.

## AI agents

Agents working on this repo (any framework) start at
[AGENTS.md](AGENTS.md) — the repo map, commands, invariants, and conventions
in one place.

The expected agent workflow is: inspect source and tests, make a focused
change, add deterministic coverage, update documentation, run targeted tests,
run Ruff, and report validation results. Agents must not contact a real HC3 or
commit scratch probes from `dev/` unless explicitly instructed.

## Pull requests

- Keep one logical concern per pull request.
- Explain the user-visible or architectural effect, not only the files changed.
- Include tests and documentation updates, or explain why they are not needed.
- List the exact validation commands that were run.
- Call out compatibility changes, new dependencies, and any remaining risks.

## License

MIT — see [LICENSE](LICENSE).
