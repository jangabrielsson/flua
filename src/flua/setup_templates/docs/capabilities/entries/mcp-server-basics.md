---
id: mcp-server-basics
topic: agents
title: flua-mcp — the agent server over the same machinery
pins:
  - tests/test_mcp.py::test_initialize_handshake
  - tests/test_mcp.py::test_resources_list_serves_the_packaged_docs
verified: flua 0.1.169
---

# flua-mcp — the agent server over the same machinery

The wheel ships `flua-mcp` as a second entry point: a Model Context
Protocol server over stdio (plus Streamable HTTP, opt-in, loopback +
token-guarded) that exposes flua to coding agents:

- **Resources** — the packaged docs (USAGE, ARCHITECTURE, the
  tutorial, specs, skills, and the capabilities entries) served as
  `flua://docs/...` URIs, with close-match suggestions on typos.
- **Tools** — `docs_list`/`docs_read`, `flua_tool` (run any
  `flua --tool` command — including `caps`), session management, and
  QA lifecycle tools.
- **Prompts** — the same guidance surfaces as the `.github/skills`.

The discipline: everything the MCP serves exists as a CLI/`--tool`
surface first — the MCP is a face of flua, never a second
implementation (ADR 0013). Hosts that only expose tools can still
reach the docs through `docs_list`/`docs_read`.
