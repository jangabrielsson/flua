# AGENTS.md — working in the flua repository

Guidance for AI agents (any framework — Claude Code, Codex, Copilot, DeepSeek,
or plain LLM tooling) working on flua. Humans: see CONTRIBUTING.md and
USAGE.md.

## What this repo is

flua is a Lua engine for Fibaro HC3 QuickApps: `lupa` (bundled Lua) hosted in
Python with an asyncio pump, a virtual clock, a message-passing bridge, and a
simulated HC3 REST API. The same QA file runs offline in the sim, online
against a real HC3, or in proxy mode (a mirror QA on the HC3).

- **Runtime**: `src/flua/` — Python engine + the HC3 runtime in `src/flua/lua/`.
- **Docs**: `USAGE.md` (user guide), `ARCHITECTURE.md` (internals),
  `README.md` (overview).
- **Examples**: `examples/` — runnable QuickApps; the test suite treats them
  as living fixtures, so keep them terminating unless their purpose is to run
  forever.
- **Specs/references**: `docs/specs/` — including `hc3-api.json`, the
  checked-in structural reference of the HC3 REST API (endpoints, parameters,
  response codes, schema fields) distilled from the official swagger.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # first time
.venv/bin/pytest tests/ -q                  # full suite (live-HC3 tests skipped)
.venv/bin/pytest tests/test_qa.py -q        # one file
.venv/bin/ruff check src/ tests/            # lint (must pass)
.venv/bin/ruff format src/ tests/           # format (line length 100)
.venv/bin/flua --check file.lua             # static check a QA
```

Python 3.11+. `lupa` is the only runtime dependency.

## How the tests work

- Almost everything runs **offline**: QAs against the simulated HC3, and
  online/proxy tests against **local mock HC3 servers** (threaded HTTP
  servers defined in the test files themselves). Never hit a real controller.
- `tests/test_hc3_live.py` / `tests/test_hc3_compat.py` are opt-in live-HC3
  suites (set `HC3_TEST=1` and configure credentials).
- Many tests bind localhost sockets (mock servers, emulator callback
  servers). A sandbox that denies socket binds will fail them — run with
  local socket access.
- Tests assert on QA stdout (`capsys`) and on mock-server request records —
  follow that pattern for new behavior: deterministic, no sleeps where a
  `wait_until`/`wait_for_output` helper exists.

## Architecture map (read before changing)

- `src/flua/engine.py` — `LuaEngine`: the lupa VM, message queues, pump.
  Single-entry discipline: Lua is entered only from `_PY.dispatch(batch)`.
- `src/flua/messages.py` — the wire format; everything crossing the bridge is
  a JSON-compatible dict. Never cross a Lua function reference.
- `src/flua/api/` — the HC3 REST API. `state.py` is the sim world;
  `routes/*.py` are pure `(SimState, ApiRequest) -> (data, status)` handlers;
  `Api.dispatch` does hybrid routing (sim first, real HC3 as fallback,
  offline-pinned QAs never reach the HC3).
- `src/flua/lua/` — the HC3 runtime in Lua: `init.lua` (pump handlers, timers,
  per-QA environments), `quickapp.lua`, `fibaro.lua`, `net.lua`, `mqtt.lua`.
- `src/flua/cli.py` — the `flua` command.
- `src/flua/tools/` — the `--tool` commands (downloadQA/uploadQA/updateQA):
  one module per tool, auto-discovered by the package registry; shared
  helpers live in `tools/common.py`.
- `src/flua/config.py` — `--%%` directive parsing, `.directives` defaults,
  mode normalization (`--%%mode:online|offline|proxy`).
- `src/flua/proxy.py` — proxy mode: proxy QA deployment on the HC3, state
  mirroring, callback server.

## Conventions and invariants

- Run `ruff check` and the relevant tests before and after any change; add a
  test for new behavior (the suite is the contract).
- API handlers stay pure; side effects go through `req.emit` /
  `req.remote` / `forward_to_proxy`.
- QA ids: engine-assigned from 5000; proxy QAs run under their HC3 id; the
  sim shadow and the HC3 device are the *same* id.
- Synchronous blocking (remote HC3 calls, debugger sockets) is a documented
  exception that freezes the pump — keep it LAN-local and rare.
- Keep `_PY` (the Lua↔Python bridge surface) minimal; convenience lives in Lua.
- `dev/` is scratch. Do not commit probes.
- Docs: behavior changes belong in `USAGE.md` (user-facing) and/or
  `ARCHITECTURE.md` (internals); directive changes belong in the directive
  table.

## Working with the user

- The project owner is the author and main developer; changes are reviewed
  commit-by-commit. Prefer small, focused, verifiable changes.
- When a behavior is intentional-but-surprising (e.g. online being the
  default mode), document it rather than silently changing it.
- Do not touch the live HC3 from tests or scripts unless explicitly asked.

## Repo-specific agent files

- `.github/copilot-instructions.md` — GitHub Copilot workspace instructions.
- `.github/instructions/quickapp-dev.instructions.md` — auto-applied to all
  `*.lua` files in Copilot.
- `.github/skills/` — Copilot slash-command skills (flua-setup,
  flua-troubleshooting, quickapp-*, hc3-rest-api, ...).
- `.github/prompts/install-qa-skills.prompt.md` — installs the above into
  another workspace.
