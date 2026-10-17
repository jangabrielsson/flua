"""flua's MCP layer (Model Context Protocol).

The machine interface for agent hosts (design: ``docs/notes/notes-mcp.md``,
packaging decision: ``docs/decisions/0010``). Ships in the fibaro-flua
wheel as the ``flua-mcp`` entry point; one-way dependency — flua core never
imports this package.

V1: stdio transport, JSON-RPC 2.0, two one-shot tools (``qa_check``,
``qa_run``). Sessions and Streamable HTTP come later.
"""
