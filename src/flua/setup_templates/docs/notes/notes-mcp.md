# Note: flua as an MCP server

Status: V1 + sessions + resources + prompts + HTTP + devices implemented
(2026-10-17) — stdio transport, JSON-RPC core, one-shot tools
(`qa_check`/`qa_run`/`qa_ui`/`devices` — the last runs to completion and
returns the final device list), the session tier (`qa_start`/`qa_probe`/
`qa_action`/`qa_sessions`/`qa_stop` on in-process engines, `qa_probe`
carries the refreshStates feed as a cursor delta), dual-era protocol
(2026-07-28 modern + 2025-06-18 legacy), the resource tier
(`flua://docs/*` from the packaged docs), the prompt tier
(`qa_debug`/`qa_skeleton`), and the Streamable HTTP transport (stateless,
opt-in `flua-mcp --http`).

## Context

Agents already get a full verify loop out of the box: self-asserting QA →
`flua --api local --instant qa.lua` → JSON logs → exit code. The MCP server
is the *machine interface* for hosts that prefer one: typed tool schemas
instead of arg-string friction, hosts with no shell at all, live stateful
sessions across tool calls, one surface for every host.

Assumption per the new MCP spec (2025-06-18): **Streamable HTTP with
stateless JSON-RPC** — one endpoint, session-less requests allowed. That
does not mean the *server* is stateless (see "sessions" below); it means
every request carries what it needs and the transport never invents hidden
state. stdio remains the simplest local transport and is worth shipping
first; the JSON-RPC core is shared between the two.

## The five questions, answered as design decisions

### 1. Should an agent be able to start a QA for test?

Yes — that is the core tool, in two shapes:

- **`qa_run` (one-shot)** — run file(s) with directives, return
  `{exit_code, logs[], verdict}`. Wraps the CLI as a subprocess
  (`flua --api local --instant --log json ...`), so the semantics are
  exactly the shipped ones: exit-code verdict, pure-JSON stdout, notices on
  stderr. This is the verify loop as a tool call.
- **`qa_start` (session)** — start a long-running engine, return a
  `session_id`. The probing tool below.

One-shot covers 90% of agent work; sessions cover debugging and
interactive exploration.

### 2. Should the server keep a QA running so the agent can probe it?

Yes — as an explicit session model, not as implicit transport state:

- `qa_start` returns a `session_id`; every probing tool takes it as an
  argument. The MCP layer stays stateless even while the server holds
  engines.
- The session runs the **in-process engine** (`from flua.engine import
  LuaEngine` on an asyncio loop in a thread) — driving `start_qa`,
  `api.dispatch`, and the message pump directly. Subprocess wrapping
  (`flua --ui`-style keep-alive) can't do inspection; the engine object can.
- Probing tools on a session: `qa_probe` (devices, QA status, logs since
  last call), `qa_action` (dispatch a device action / inject a UI event /
  call a QA method), `qa_stop`.
- **TTL + cleanup are part of the contract**: sessions idle out (default
  e.g. 10 min), `qa_stop` and server shutdown kill engines — the current
  sessions are listable via `qa_sessions`. An agent that forgets to stop a
  session must not leak engines forever.

### 3. Should it be able to start several QAs?

Yes — flua's engine is already an ensemble runtime (QAs calling each other
via `fibaro.call`, multi-QA exit aggregation). Both shapes take lists:

- `qa_run` accepts several main files (the CLI already does) — one engine,
  N QAs, aggregated verdict.
- `qa_start` likewise; `qa_probe`/`qa_action` address QAs by id (5000+,
  from the probe result).

No new engine work needed — the tool layer just passes lists through.

### 4. How to help with QA coding knowledge (APIs, best practices)?

Knowledge is **resources and prompts**, not tools — tools stay imperative
and typed:

- **Resources** (`flua://docs/…`): USAGE.md, ARCHITECTURE.md, the
  walkthroughs, the tutorial chapters, `docs/specs/hc3-api.json` (the
  endpoint reference), and `docs/mcp.md`. Served from the installed
  package (`setup_templates/docs`, synced by `scripts/sync-skills.sh`), so
  the MCP works from pip alone. Text only, paths canonicalized, traversal
  rejected. (Skills are not resources — the `.github/skills` bodies stay a
  repo-level mechanism; the docs overlap covers the same knowledge.)
- **Prompts**: `qa_debug` (error + file → structured next-step guidance:
  read the log shape, `--check`, shrink-the-problem) and `qa_skeleton`
  (a runnable QA template with flua-test assertions and the
  deferred-onInit pattern) — implemented, see `docs/mcp.md`.
- Best practices live in the docs they already live in; the MCP just makes
  them retrievable by URI. (Copilot hosts get the same knowledge via the
  existing `.github/skills` — MCP resources are the transport for hosts
  that don't read repo files.)

### 5. Can we use flua as-is and wrap the command in an MCP server that starts/stops flua?

Yes — that is exactly the V1, and it stays valid for V2:

- **V1 (recommended first)**: the one-shot tools are thin subprocess
  wrappers around the CLI. Nothing new in flua itself — `--log json`,
  `--check`, `--tool ui`, exit codes already provide the machine interface.
- **V2**: sessions import the engine in-process (the MCP server is Python
  anyway; `fibaro-flua` ships the engine). The CLI stays the reference
  semantics; the in-process path reuses the same objects.
- What flua might need to *add* (small, later): nothing blocking. Nice-to-
  haves: `--log json` for `--tool ui` output, a stable `flua --version
  --machine` flag, maybe `--session`-style stdin/stdout control for
  subprocess-backed sessions if in-process import ever proves awkward.

## Tool surface (draft)

| Tool | Shape | Transport |
|---|---|---|
| `qa_check` | files → `{ok, findings[]}` | one-shot (subprocess) |
| `qa_run` | files, directives(mode/instant/speed/vars) → `{exit_code, logs[], verdict}` | one-shot (subprocess) |
| `devices` | files, directives → `{exit_code, devices[]}` (run to completion, then the final device list) | one-shot (in-process engine) |
| `qa_start` | files, directives → `{session_id, qa_ids[]}` | in-process engine |
| `qa_probe` | session_id → `{devices[], qas[], logs[], refreshStates}` | in-process engine |
| `qa_action` | session_id, qa_id, action, args → result | in-process engine |
| `qa_ui_text` | file → text rendering | one-shot (`--tool ui`) |
| `qa_stop` / `qa_sessions` | session control | server state |

Resources (implemented): `flua://docs/<file>` — the packaged docs tree,
e.g. `flua://docs/USAGE.md`, `flua://docs/walkthroughs.md`,
`flua://docs/tutorial/{chapter}.md`, `flua://docs/specs/hc3-api.json`,
`flua://docs/mcp.md`. Prompts (implemented): `qa_debug`, `qa_skeleton`.

## Transport notes (stateless spec)

- One JSON-RPC implementation, two transports, both shipped: **stdio**
  (local hosts, the default) and **Streamable HTTP** (stateless mode —
  `POST /mcp`, no session id, no SSE; `flua-mcp --http`, loopback by
  default, `FLUA_MCP_TOKEN` required beyond loopback). Remote and browser
  hosts use HTTP; local hosts keep stdio. Dependency-free holds: stdlib
  `http.server` (ADR 0011).
- Secrets: HC3 credentials come from the server's environment (`.env`
  chain), never from tool arguments — online/proxy runs reuse flua's own
  env resolution.
- The four deltas from notes-agents.md (typed schemas, shell-less hosts,
  live sessions, one standard surface) map onto the table above; sessions
  are the only stateful piece and they are explicit by design.

## Open questions — all resolved

1. ~~V1 transport order — stdio first, or Streamable HTTP first?~~ Both
   shipped: stdio default, `--http` opt-in (ADR 0011).
2. ~~In-process sessions: one shared event loop per server, or one thread +
   loop per session?~~ One engine per session on its own loop/thread
   (sessions.py) — per-session isolation, mirroring how the tests drive
   engines.
3. ~~Should the server cap `qa_run` concurrency?~~ Yes —
   `MAX_CONCURRENT_RUNS` (4) shared by `qa_run` and `devices`; extra runs
   fail fast with `isError` (server busy), never queue.
4. ~~Do we pin the MCP spec version and reject old-protocol clients?~~
   `SUPPORTED_VERSIONS` is the pin: unsupported per-request versions answer
   `-32022`, and the legacy `initialize` era is still served (dual-era).
5. ~~Should `qa_probe` include the refreshStates feed?~~ Yes — implemented:
   the feed rides the same cursor-delta machinery as the logs (HC3 polling
   shape `{status, last, changes, events}`).
6. ~~Naming: `qa_*` prefix everywhere, or drop it?~~ `qa_*` for the QA
   tools; the docs tools are their own `docs_*` family (the same tree the
   resource tier serves — see the dogfood note below).

## Dogfood findings

Copilot (2026-10-18, two rounds): the host consumes **tools** well
(`qa_check`/`qa_start`/`qa_probe`/`qa_stop` drove a full build-test loop),
but never touched `resources/read` even with discover instructions pointing
at it — it web-searched for knowledge that ships in the wheel (PyPI,
flua.dev, deepwiki, a guessed repo name). Likely the client exposes tools
only. Fix: the same docs tree is also served as `docs_list`/`docs_read`
**tools** (tools are the lowest common denominator across hosts), and the
instructions name the tool form first. Second finding: a wrong `--%%type`
had no local way to enumerate valid types — `flua --tool catalog` now lists
them, and the error names close matches.
