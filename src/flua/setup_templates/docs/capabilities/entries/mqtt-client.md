---
id: mqtt-client
topic: runtime-net
title: mqtt.Client — the HC3's MQTT 3.1.1 API
pins:
  - tests/test_mqtt.py::test_mqtt_connect_subscribe_publish_roundtrip
  - tests/test_mqtt.py::test_tls_use_sni_option
verified: flua 0.1.166
---

# mqtt.Client — the HC3's MQTT 3.1.1 API

The `mqtt` global (not `net.*`) — the HC3's documented MQTT client:

- `mqtt.Client` with the standard callbacks: connect →
  subscribe → publish round trips (pinned), refused connects report,
  unsubscribe works, and malformed SUBACKs error *and drain* cleanly
  (no stuck connections).
- TLS via the `useSNI` option (pinned); `MQTTConnectReturnCode` maps
  the protocol's connect codes.
- A mock broker (threaded, in the test suite) exercises the whole
  flow offline; `examples/` ships MQTT QAs, including MQTT-over-
  WebSocket.

The engine pumps MQTT I/O through the same per-QA suspension as other
network classes — a broker round trip never blocks the pump.
