---
id: integration-protocol-workflow
topic: patterns
title: Implementing an integration protocol — the flua workflow
pins:
  - tests/test_server.py::test_mock_server_example_self_tests
  - tests/test_qa.py::test_examples_qa_pair_calls_each_other
verified: flua 0.1.169
---

# Implementing an integration protocol — the flua workflow

The flagship agent task. The recipe that works, in order:

1. **Pick the transport** — HTTP (`net.HTTPClient`, SSE for feeds),
   WebSocket (`net.WebSocketClient`, push via `net.WebSocketServer`),
   MQTT (`mqtt.Client`), or raw TCP/UDP sockets — each has a pinned
   capability entry.
2. **Model the far side** — implement the external system/device as a
   *sim QA* speaking the real protocol (the Solaredge mock serves both
   wire bases; `examples/mockServer.lua` self-tests all four server
   kinds). Your QA under test then talks to a real protocol peer
   offline — see `modeling-external-devices`.
3. **Keep the pump alive** — a QA with no pending work drains in flua:
   timers, subscriptions, or `_FLUA.keepAlive()`.
4. **Respect the bridge** — everything crossing Lua↔Python stays
   JSON-compatible; binary rides as byte arrays. `--bridge-debug`
   makes a dropped payload loud.
5. **Pin it** — the protocol round trips become tests against a
   localhost mock peer (see `mock-peer-testing`), so the integration
   cannot silently rot.

QAs can also drive *each other*: name lookup + `fibaro.call` actions
(`examples/qa3.lua` + `qa4.lua`, pinned) — the pattern for splitting a
big integration into cooperating QAs.
