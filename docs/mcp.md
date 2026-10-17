# flua-mcp — the MCP server

Machine interface to flua for agent hosts (Claude Desktop, Copilot, …).
Ships in the fibaro-flua wheel as the `flua-mcp` console script; one version
with flua (design: `docs/notes/notes-mcp.md`, packaging: ADR 0010).

## Protocol surface (current)

- **Transport**: stdio — newline-delimited JSON-RPC 2.0 on stdin/stdout.
- **Protocol version**: `2025-06-18` (the stateless-session spec). Sessions
  are not used yet; every request is self-contained.
- **stdout is pure JSON-RPC** — one response line per request; server
  diagnostics go to stderr. Agents can parse stdout unconditionally.
- **Capabilities**: `tools` only. Resources and prompts come later.

| Method | Purpose |
|---|---|
| `initialize` | handshake → `{protocolVersion, capabilities, serverInfo}` |
| `ping` | liveness → `{}` |
| `tools/list` | the tools with their JSON-Schema inputs |
| `tools/call` | run one tool → `{content: [{type: "text", text: <json>}], isError}` |
| `notifications/initialized`, `notifications/cancelled` | accepted, never answered |

Error semantics: invalid JSON/requests and unknown methods answer with the
standard JSON-RPC error codes (`-32700`/`-32600`/`-32601`); bad *tool
arguments* and tool failures travel in the result as `isError: true` —
never as a JSON-RPC error. Unknown tool names are JSON-RPC errors
(`-32601`), per the spec.

## Tools (V1)

### `qa_check`

Static checks — same layers as `flua --check`: Lua syntax, unknown `--%%`
directives, deprecated HC3 APIs, and every `--%%file` include. Does not run
the QA.

```json
{"name": "qa_check", "arguments": {"files": ["main.lua", "other.lua"]}}
```

Result: `{"ok": bool, "findings": [{"file", "severity", "message"}]}` —
`ok` is false when any finding is `error`-severity.

### `qa_run`

Runs QA files to completion in the emulator and returns the outcome.
One-shot: the run ends when the QAs drain (interactive probing is a later
session tool).

```json
{"name": "qa_run", "arguments": {"files": ["main.lua"], "instant": true}}
```

Arguments: `files` (required), `mode` (`local`|`remote`), `instant`,
`speed`, `start` (virtual start time, e.g. `"2027/10/6 18:30:00"`),
`timeout` (wall seconds, default 120).

Result: `{"exitCode", "logs", "verdict"}` — `logs` are the QA's `--log
json` lines, `verdict` the stderr notices (exit attribution). A nonzero
`exitCode` is a failed run.

## Running it

```bash
flua-mcp                 # stdio JSON-RPC server (reads stdin, answers stdout)
flua-mcp --version       # flua-mcp 0.1.40 (protocol 2025-06-18)
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
  complete and typed; never parse `tools/list` prose.
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

- Done: stdio core, `qa_check`, `qa_run`, packaging, tests
  (`tests/test_mcp.py` — core, transport, tools, end-to-end).
- Planned: session tools (`qa_start`/`qa_probe`/`qa_action` on the
  in-process engine), more one-shot tools (`qa_ui` from `--tool ui --json`,
  `devices` from the REST feeds), resources/prompts (`flua://docs/*`), and
  the Streamable HTTP transport.
