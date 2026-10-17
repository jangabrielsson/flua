"""flua's MCP layer (Model Context Protocol).

The machine interface for agent hosts (design: ``docs/notes/notes-mcp.md``,
packaging decision: ``docs/decisions/0010``). Ships in the fibaro-flua
wheel as the ``flua-mcp`` entry point; one-way dependency — flua core never
imports this package.

Two transports share one dispatch core: stdio (newline-delimited JSON-RPC,
the default) and Streamable HTTP (stateless mode, ``flua-mcp --http``).
Tools: ``qa_check``/``qa_run``/``qa_ui`` one-shot, the session tier
(``qa_start``/``qa_probe``/``qa_action``/``qa_sessions``/``qa_stop``),
the docs as resources (``flua://docs/*``), and two prompts
(``qa_debug``/``qa_skeleton``).
"""
