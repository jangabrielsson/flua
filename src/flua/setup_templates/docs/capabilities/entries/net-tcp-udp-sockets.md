---
id: net-tcp-udp-sockets
topic: runtime-net
title: net.TCPSocket / net.UDPSocket — raw sockets from QA code
pins:
  - tests/test_tcp.py::test_tcp_echo_roundtrip
  - tests/test_server.py::test_tcp_udp_ws_servers_round_trip
verified: flua 0.1.166
---

# net.TCPSocket / net.UDPSocket — raw sockets from QA code

The raw transport clients (the HC3's `net.*` socket surface):

- `net.TCPSocket` — connect, send/receive (text and binary round trips
  are pinned), persistent connections.
- `net.UDPSocket` — datagram send/receive; the engine-side UDP socket
  binds an ephemeral socket synchronously.

Both run their I/O on worker threads (the dedicated socket pool) so a
blocked peer never freezes the pump — the same discipline as the other
net classes. Binary data crosses the bridge as byte arrays
(`_FLUA.escapeBytes`/`unescapeBytes`); keep payloads JSON-compatible.

For the *server* side, see `net-fixture-servers`; for the fixture
server round trips (tcp/udp/ws in one test), the pinned test above.
