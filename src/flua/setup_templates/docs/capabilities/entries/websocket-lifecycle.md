---
id: websocket-lifecycle
topic: runtime-net
title: WebSocket lifecycle — close fires disconnected once; fresh client per reconnect
pins:
  - tests/test_websocket.py::test_websocket_close_before_connected_fires_only_disconnected
  - tests/test_websocket.py::test_server_initiated_close_sends_exactly_one_close_frame
verified: flua 0.1.171
---

# WebSocket lifecycle — close fires disconnected once; fresh client per reconnect

The reconnect semantics an integration always needs (USAGE.md carries the
same contract):

- `ws:close()` fires the `disconnected` listener **exactly once** —
  whether or not the handshake had completed; closing before connect
  delivers only `disconnected` (pinned).
- A client instance owns one connection. For reconnect logic the
  supported pattern is a **fresh client per reconnect** (construct →
  connect → listen), not re-`connect()` on a failed/closed instance —
  the defensive pattern the HASS hardening round settled on.
- The server side mirrors it: `disconnected` fires once per connection,
  and `ws:disconnect(conn)` closes from the server's side with exactly
  one close frame (pinned).

Both sides' disconnect events are asynchronous — never assert one side
saw its event from the other side's handler (see the barrier pattern in
`websocket-server-push`).
