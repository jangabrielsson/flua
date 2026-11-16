---
id: bridge-debug
topic: debugging
title: --bridge-debug — when the Lua↔Python bridge drops a payload
pins:
  - tests/test_bridge_debug.py::test_bridge_debug_dumps_failing_payload_and_records_event
verified: flua 0.1.166
---

# --bridge-debug — when the Lua↔Python bridge drops a payload

The bridge between Lua and Python rejects payloads it cannot convert
(non-JSON-compatible values crossing a wire that must stay JSON). When
that happens silently, the symptom is a QA action that "did nothing".

`--bridge-debug` makes it loud: the failing payload is dumped and a
system event recorded (pinned) — the first diagnostic an agent should
turn on for a mystery no-op. The discipline behind it: everything
crossing the bridge is JSON-compatible; never cross a Lua function
reference (AGENTS.md). Off by default, one flag when things smell.
