---
id: mock-peer-testing
topic: testing
title: Mock peers — localhost servers in the test files, not external processes
pins:
  - tests/test_server.py::test_require_loads_sibling_test_libs
  - tests/test_mqtt.py::test_mqtt_connect_subscribe_publish_roundtrip
verified: flua 0.1.169
---

# Mock peers — localhost servers in the test files, not external processes

The pinned idiom for protocol tests: a threaded mock server bound to
localhost *inside the test file* (the mock HC3 in `test_hc3.py`, the
mock broker in `test_mqtt.py`, the mock Modbus in
`test_modbus_mock.py`). The suite never touches a real controller or a
real peer.

- Test scaffolding (mock servers etc.) can live in a sibling file
  loaded with `require()` — runtime-only, never part of the QA's
  package (pinned).
- Assert on the mock's request records and the QA's stdout; no sleeps
  where a `wait_until`/`wait_for_output` helper exists (AGENTS.md).
- Many tests bind localhost sockets — a sandbox that denies socket
  binds fails them; run with local socket access.

For the in-QA alternative (the server *inside* a QA), see
`net-fixture-servers`; for modeling the far side, see
`modeling-external-devices`.
