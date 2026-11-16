---
id: net-fixture-servers
topic: runtime-net
title: net.HTTPServer / TCPServer / UDPServer — in-QA fixture servers
pins:
  - tests/test_server.py::test_tcp_udp_ws_servers_round_trip
  - tests/test_server.py::test_handler_error_is_http_500
  - tests/test_server.py::test_tcp_server_persistent_connection_and_binary
verified: flua 0.1.166
---

# net.HTTPServer / TCPServer / UDPServer — in-QA fixture servers

flua's server implementations — a QA can *be* the server:

- `net.HTTPServer():listen(port, handler)` — the handler takes a
  request table (`method/url/headers/body`) and returns a response; a
  handler that raises answers 500 with the error text (pinned). Port 0
  picks a free one; the bound port is reported.
- `net.TCPServer` — persistent connections with binary payloads
  (pinned); `net.UDPServer` — datagram service.
- `net.WebSocketServer` — the request/response + push + disconnect
  story lives in `websocket-server-push`.

The classic fixture pattern: run the server in a test QA, have the QA
under test connect to it — deterministic tests without external
processes, and the same code runs on the HC3.
