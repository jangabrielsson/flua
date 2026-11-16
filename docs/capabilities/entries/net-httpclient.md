---
id: net-httpclient
topic: runtime-net
title: net.HTTPClient — REST, SSE streaming, and clean cancellation
pins:
  - tests/test_http.py::test_http_sse_streams_events
  - tests/test_http.py::test_qa_exit_cancels_open_sse_stream
verified: flua 0.1.166
---

# net.HTTPClient — REST, SSE streaming, and clean cancellation

The QA-side HTTP client (the HC3's `net.HTTPClient`):

- Request/response with `success`/`error` callbacks; timeouts, headers,
  and body options.
- **SSE streaming** — server-sent events arrive incrementally as they
  stream (pinned): the channel for long-lived feeds (energy meters,
  assistant streams).
- Open streams are cancelled cleanly when the QA exits (pinned) — no
  orphaned connections holding the pump.
- TLS variants: `net.WebSocketClientTls` does **no certificate
  verification by default** (HC3 behavior); `checkCertificate` opts in.

In-QA server fixtures exist on the other side: `net.HTTPServer`,
`TCPServer`, `UDPServer`, `WebSocketServer` — see the
`websocket-server-push` entry for the push story.
