---
id: debugger
topic: debugging
title: The mobdebug debugger — VS Code attach over --debugger
pins:
  - tests/test_qa.py::test_mobdebug_e_bootstrap_does_not_consume_qa_id
verified: flua 0.1.170
---

# The mobdebug debugger — VS Code attach over --debugger

flua embeds the mobdebug debugger (`--debugger` / the VS Code
extension's attach flow): breakpoints, step, and Lua state inspection
against a running QA.

- The `mobdebug_e` bootstrap is a *plain library*, not a QA — it never
  consumes a QA id or hides the main script's mode (pinned), so the
  debugger's scaffolding stays invisible to the device tree.
- A debugger pause does **not advance virtual time** (the clock
  freezes during the pause) — os.time()-relative logic stays coherent
  across stepping.
- The VS Code extension wires check-on-save diagnostics, explorer tool
  menus, and the debugger attach.

For "the bridge dropped something" instead, see `bridge-debug`; for
run history, `syslog-and-tracing`.
