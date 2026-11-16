---
id: websocket-server-push
topic: runtime-net
title: net.WebSocketServer can push and disconnect — event-driven server protocols
pins:
  - tests/test_server.py::test_ws_server_push_disconnect_and_events
verified: flua 0.1.165
---

# net.WebSocketServer can push and disconnect — event-driven server protocols

flua's `net.WebSocketServer` is a full server, not just request/response:

- `ws:listen(port, handler)` — the handler returns a reply, like a
  request/response endpoint.
- `ws:send(conn, message)` — push an **unsolicited** frame to a client
  (event-driven protocols, subscriptions, notifications).
- `ws:disconnect(conn)` — close a connection server-side.
- Lifecycle events per connection: `connected` / `disconnected` (plus
  `error`/`dataReceived` on the client side), via `addEventListener`.

Pattern: `ws:addEventListener('connected', ...)` tracks clients, and a
`setTimeout`/event source pushes to them. The disconnect events on both
sides are asynchronous — never assert one side saw its event from the
other side's handler (see the pinned test's barrier pattern).

For reacting to *device* changes, `RefreshStateSubscriber` over the
refreshStates feed is the HC3 mechanism — see `docs/forum/11-refreshstate.html`.
