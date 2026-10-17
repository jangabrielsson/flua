# 0011 — flua-mcp speaks Streamable HTTP (stateless mode)

- **Status:** active
- **Date:** 2026-10-17

## Context

flua-mcp shipped stdio-only (ADR 0010). stdio covers local hosts (Claude
Desktop, Copilot workspace mode, Claude Code), but not hosts that cannot
spawn a local process: cloud/remote agents, browser-hosted MCP clients, and
one-server-many-clients setups. For flua specifically this matters because
the real HC3 sits on the user's LAN — a remote agent that wants `mode=remote`
runs must reach a server on that network, and stdio cannot be that.

The session tier was already designed transport-stateless (explicit
`sessionId` tool arguments, no transport state), so the 2026-07-28
stateless Streamable HTTP mode maps onto it directly: plain HTTP POST +
JSON-RPC, no SSE, no `Mcp-Session-Id` header, no server-side request state.

## Decision

`flua-mcp --http [HOST:PORT]` serves the **same dispatch core** over
Streamable HTTP in stateless mode:

- **One endpoint** `POST /mcp`; notifications answer `202` with no body,
  responses answer `200`. `GET`/`DELETE` answer `405` (no SSE);
  `Mcp-Session-Id` requests answer `404` — sessions are tool arguments,
  never transport state. CORS is permissive (wildcard origin; auth is a
  header, not a cookie) so browser hosts work.
- **Opt-in, loopback by default**: `--http` alone binds `127.0.0.1:8091`.
  stdio remains the default and the recommended local transport.
- **Auth is env-only**: `FLUA_MCP_TOKEN` (a bearer token). The constructor
  **refuses to bind a non-loopback address without one** — the guarantee
  lives in the mechanism, not in documentation. Request bodies are
  size-capped (10 MiB) and rejected with `413`.
- **Dependency-free**: stdlib `http.server` (threaded); the `lupa`-only
  rule from ADR 0010 stands. JSON-RPC dispatch, protocol-version checks,
  tools, resources, and prompts are the same objects stdio uses — one
  implementation, two transports.

## Consequences

- Remote agents can drive flua through a tunnel or a LAN-exposed,
  token-guarded port; browser hosts and shared-server setups work.
- The transport adds an attack surface (probe/action tools expose device
  state; HC3 credentials live in the server env) — that is exactly what the
  loopback default, the non-loopback token requirement, and the body cap
  mitigate. Token auth is per-request (`hmac.compare_digest`).
- `tests/test_mcp_http.py` pins the transport: round-trips, spec rules
  (202/405/404/CORS), auth, the non-loopback guard, and the real CLI.
- Session *mode* HTTP (SSE, `Mcp-Session-Id`) stays out of scope: the
  session tier already carries its state in tool arguments, so stateless
  mode loses nothing.
