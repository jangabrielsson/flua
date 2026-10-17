# flua-mcp — the MCP server

Machine interface to flua for agent hosts (Claude Desktop, Copilot, …).
Ships in the fibaro-flua wheel as the `flua-mcp` console script; one version
with flua (design: `docs/notes/notes-mcp.md`, packaging: ADR 0010).

## Protocol surface (current)

- **Transport**: stdio — newline-delimited JSON-RPC 2.0 on stdin/stdout.
- **Spec revision**: dual-era. The **modern** surface (2026-07-28) needs no
  handshake — every request carries its protocol version in `params._meta`
  and `server/discover` (required) lists `supportedVersions`. The **legacy**
  `initialize` handshake (2025-06-18) is still served for older clients.
  Unsupported versions answer error `-32022` with `{supported, requested}`.
- **stdout is pure JSON-RPC** — one response line per request; server
  diagnostics go to stderr. Agents can parse stdout unconditionally.
- **Capabilities**: `tools` and `resources` (the packaged docs as
  `flua://docs/*`). Prompts come later.

| Method | Era | Purpose |
|---|---|---|
| `server/discover` | modern | `{resultType, supportedVersions, capabilities, _meta.serverInfo, instructions}` |
| `initialize` | legacy | handshake → `{protocolVersion, capabilities, serverInfo}` |
| `ping` | both | liveness → `{}` |
| `tools/list` | both | the tools with their JSON-Schema inputs (`resultType: "complete"`) |
| `tools/call` | both | run one tool → `{resultType, content, isError}` |
| `resources/list` | both | every doc resource → `{resultType, resources: [{uri, name, title, description, mimeType}]}` |
| `resources/read` | both | one resource's text → `{resultType, contents: [{uri, mimeType, text}]}` |
| `notifications/initialized`, `notifications/cancelled` | legacy | accepted, never answered |

Error semantics: invalid JSON/requests and unknown methods answer with the
standard JSON-RPC error codes (`-32700`/`-32600`/`-32601`); bad *tool
arguments* and tool failures travel in the result as `isError: true` —
never as a JSON-RPC error. Unknown tool names are JSON-RPC errors
(`-32601`), per the spec.

## Tools

### One-shot

#### `qa_check`

Static checks — same layers as `flua --check`: Lua syntax, unknown `--%%`
directives, deprecated HC3 APIs, and every `--%%file` include. Does not run
the QA.

```json
{"name": "qa_check", "arguments": {"files": ["main.lua", "other.lua"]}}
```

Result: `{"ok": bool, "findings": [{"file", "severity", "message"}]}` —
`ok` is false when any finding is `error`-severity.

#### `qa_run`

Runs QA files to completion in the emulator and returns the outcome.
One-shot: the run ends when the QAs drain.

```json
{"name": "qa_run", "arguments": {"files": ["main.lua"], "instant": true}}
```

Arguments: `files` (required), `mode` (`local`|`remote`), `instant`,
`speed`, `start` (virtual start time, e.g. `"2027/10/6 18:30:00"`),
`timeout` (wall seconds, default 120), `filter` (`{levels?, match?}` —
server-side log narrowing; the agent asks for "just the failures" instead
of shelling out).

Result: `{"exitCode", "logs", "verdict", "summary"}` — `logs` are the QA's
`--log json` lines, `verdict` the stderr notices, and `summary` the answer
without jq: level counts and flua-test `pass`/`fail`/`failures` tallies. A
nonzero `exitCode` is a failed run.

#### `qa_ui`

The structured UI of one QA: `{name, type, useUiView, elements, callbacks}`
(the `flua --tool ui --json` payload) — elements carry name/text/value/
options, so an agent can read a QA's controls without parsing prose.

```json
{"name": "qa_ui", "arguments": {"files": ["main.lua"]}}
```

### Sessions (live probing)

A session is a running flua engine an agent can probe across tool calls.
The MCP transport itself stays stateless: the `sessionId` is an explicit
argument, never connection state.

- **`qa_start`** — `{files, mode?, instant?, speed?, start?, ttl?}` →
  `{sessionId, qaIds}`. Idle sessions are reaped after `ttl` seconds
  (default 600).
- **`qa_probe`** — `{sessionId}` → `{devices, qas, debugMessages,
  systemEvents}`. The two log feeds are **deltas since the previous probe**
  (cursor-based) — repeated probes only show what is new.
- **`qa_action`** — `{sessionId, qaId, action, args?}` → `{status}`;
  dispatches `POST /devices/{id}/action/{action}` into the running engine
  (reaches the QA's `callAction`).
- **`qa_sessions`** — `{}` → `{sessions: [{sessionId, qaIds, ageSeconds}]}`.
- **`qa_stop`** — `{sessionId}` → `{stopped}`. Unknown session ids are
  `isError` tool results.

Sessions run in-process (each engine owns its asyncio loop on a daemon
thread, like the test suite drives them) and are always torn down when the
stdio pipe closes — an agent cannot leak engines.

## Resources

The docs ship in the wheel (`src/flua/setup_templates/docs`, synced from the
repo by `scripts/sync-skills.sh`) and are served as MCP resources under the
`flua://docs/` scheme — so a host without a repo checkout can still read the
same knowledge a local agent reads from the checkout. Text files only (the
tutorial PDF is not served).

```json
{"method": "resources/read", "params": {"uri": "flua://docs/USAGE.md"}}
```

Examples: `flua://docs/USAGE.md`, `flua://docs/ARCHITECTURE.md`,
`flua://docs/tutorial/01-install.md`, `flua://docs/decisions/0010-mcp-ships-in-the-wheel.md`,
`flua://docs/specs/hc3-api.json`, `flua://docs/mcp.md` (this page).
`resources/list` enumerates them with mime types and curated descriptions;
paths are canonicalized and traversal (`..`) is rejected with a JSON-RPC
error, never a filesystem escape.

## Running it

```bash
flua-mcp                 # stdio JSON-RPC server (reads stdin, answers stdout)
flua-mcp --version       # flua-mcp 0.1.40 (protocols 2026-07-28, 2025-06-18)
```

Register it as a stdio MCP server in the host's config — no extra install,
no extra dependencies:

- **Claude Desktop** (`claude_desktop_config.json`):

  ```json
  {"mcpServers": {"flua": {"command": "flua-mcp"}}}
  ```

- **Copilot / other `mcp.json` hosts** (uses the interpreter flua runs on):

  ```json
  {"mcpServers": {"flua": {"command": "python", "args": ["-m", "flua.mcp.server"]}}}
  ```

## What agents can rely on

- `initialize` and `tools/list` are the discovery surface — schemas are
  complete and typed; never parse `tools/list` prose. `resources/list` is
  the same for docs: read `resources/read`, don't guess file locations.
- Tool results are JSON inside the MCP `text` content block (single block).
- `qa_run` never talks to a controller unless `mode: "remote"` is explicit;
  the default is the offline sim.
- Credentials: `mode: "remote"` uses the server process's environment
  (`HC3_URL`/`HC3_USER`/`HC3_PASSWORD`, the same chain `flua` uses) — never
  tool arguments.
- Runs are bounded (`timeout`), and every tool failure is either an
  `isError` result or a JSON-RPC error — the server process never dies on a
  bad request.

## Status & next

- Done: stdio core, one-shot tools (`qa_check`, `qa_run`, `qa_ui`), the
  session tier (`qa_start`/`qa_probe`/`qa_action`/`qa_sessions`/`qa_stop`),
  the resource tier (`flua://docs/*`), packaging, tests (`tests/test_mcp.py`).
- Planned: prompts (`prompts/list`/`prompts/get`), more one-shot tools
  (`devices` from the REST feeds), and the Streamable HTTP transport.
