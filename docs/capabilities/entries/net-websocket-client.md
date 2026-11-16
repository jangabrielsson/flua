---
id: net-websocket-client
topic: runtime-net
title: net.WebSocketClient — the client side (TLS without cert checks)
pins:
  - tests/test_websocket.py::test_websocket_echo_roundtrip
  - tests/test_websocket.py::test_wss_self_signed_default_skips_verification
verified: flua 0.1.166
---

# net.WebSocketClient — the client side (TLS without cert checks)

The client half of the WebSocket story (the push/server half is
`websocket-server-push`):

- `net.WebSocketClient()` — connect with custom headers, text and
  binary round trips (pinned); a connect refusal fires `error`, and
  closing before connect fires only `disconnected` (pinned).
- `net.WebSocketClientTls` — **no certificate verification by
  default** (HC3 behavior): self-signed wss connects (pinned);
  `checkCertificate` opts in. Concurrent sends are serialized, and a
  server-initiated close sends exactly one close frame.
- The `Sub-Protocol` header is canonical and validated; text sends
  reject invalid UTF-8 rather than corrupting frames.

The `--%%debug:ws=true` channel logs byte-level traffic — handshake
leftovers, per-frame rx/tx with masked previews, close codes.
