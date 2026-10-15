# Note: an MQTT broker for testing the mqtt client

Status: idea, not scheduled. Brought up 2026-10-11; revisit before scoping work.

## The idea

The HC3 has no MQTT broker of its own — QAs always talk to an external one.
flua would provide a broker purely to aid testing the `mqtt` client: run a
QA against a local broker instead of a public one (hivemq throttles, needs
internet). Python module (e.g. `src/flua/mqtt_broker.py`) alongside the
client, likely exposed to QA code as `net.MQTTBroker()` — the MQTT sibling
of the other `net.*Server` mock servers (forum post 8): a handler-driven
server QAs and test code can script in Lua.

## Why build rather than import

- The wire codec already exists in `src/flua/mqtt.py` (dependency-free MQTT
  3.1.1 over stdlib sockets, threaded).
- `tests/test_mqtt.py` already contains a working `MiniBroker` (~100 lines:
  CONNECT/SUBSCRIBE/PUBLISH fan-out/PING/DISCONNECT, QoS 1 PUBACK) — the
  seed and the proof of design.
- The only credible pure-Python broker library is `amqtt` (ex-hbmqtt):
  asyncio-based (friction with flua's threaded blocking sockets), pulls
  dependencies (repo law: `lupa` is the only runtime dependency), and has a
  spotty maintenance record. Not obviously cheaper than ~400 lines we own.

## Scope sketch

- QoS 0/1 fully; QoS 2 receive handshake tolerated, send-side downgraded to
  QoS 1 (the client already does the same, documented).
- Topic matching done right: `+` single-level and `/#` multi-level
  wildcards (the test broker's matcher only does exact + `/#` suffix).
- Retained messages, last-will, keep-alive expiry, multi-client fan-out.
- Reuse/extract the wire helpers from `mqtt.py` so client and broker share
  one codec.

## Open questions

- Lua surface: `net.MQTTBroker()` — mirror the other `net.*Server` mocks
  (`net.HTTPServer`/`net.TCPServer` are built with the same `serverClass`
  helper: an optional port argument, 0 = ephemeral with the real port
  readable immediately, handler-driven in Lua)? Or a plain engine-side
  broker the test suite and examples start directly?
- How sessions/retained state are exposed for assertions (inspect through
  the Lua surface or a Python API).
- Whether TLS (`mqtts://`) on the broker is in scope for v1 (client TLS is
  done; broker-side certs add setup friction — probably defer).
