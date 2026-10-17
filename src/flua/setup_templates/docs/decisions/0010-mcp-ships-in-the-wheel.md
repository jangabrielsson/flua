# 0010 — the MCP server ships in the fibaro-flua wheel

- **Status:** active
- **Date:** 2026-10-17

## Context

The MCP layer (design: `docs/notes/notes-mcp.md`) needs a home. Two options:
a separate package/distribution, or the same repo and the same PyPI
artifact. A separate package would force version pinning against flua,
duplicate the release pipeline, and lose direct access to the engine —
while the server is a thin machine interface over things flua already ships
(`--check`, the CLI, the engine, the tools).

## Decision

The MCP server lives in **this repo** (`src/flua/mcp/`) and ships in the
**fibaro-flua wheel** as a second console script: `flua-mcp =
"flua.mcp.server:main"`. One version, one release, one install.

- **One-way dependency**: `flua.mcp` imports `flua.engine`/`flua.tools`/
  `flua.check`; flua core never imports `flua.mcp`. The layer is always
  shipped but never loaded unless the entry point runs — zero import cost
  for everyone else.
- **Dependency-free V1**: stdio JSON-RPC needs no SDK (plain stdlib); the
  stateless Streamable HTTP mode later is plain `http.server` + JSON-RPC.
  The core `lupa`-only dependency rule stands.
- **Transport order**: stdio first (local hosts); Streamable HTTP after the
  tools stabilize.

## Consequences

- `pip install fibaro-flua` provides both `flua` and `flua-mcp`.
- The existing test suite covers the MCP layer (subprocess JSON-RPC on
  stdin/stdout); the CI matrix (3.11–3.14) applies unchanged.
- Host registration (Claude Desktop/Copilot config) stays documentation —
  USAGE.md + the skills — never code.
- Sessions (the stateful tier from notes-mcp.md) will use the in-process
  engine; the one-shot tools already wrap the shipped CLI so semantics
  cannot drift.
