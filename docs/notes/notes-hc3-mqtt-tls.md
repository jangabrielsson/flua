# Note: the HC3 MQTT client vs modern app-facing brokers (field report)

Status: field knowledge (2026-11-11) — a forum user's BMW CarData broker
failure, diagnosed from flua's MQTT contract model. File-away material if
we (or flua users) hit the same shape.

## The symptom

The HC3's native `mqtt.Client` could not connect to a modern app-facing
broker (`customer.streaming-cardata.bmwgroup.com:9000`, MQTT over TLS):

- `mqtt.Client.connect()` returned quickly; the connect callback received
  **167773230** (`0xA00042E`) and no `connected`, `error`, or `closed`
  event ever fired.
- Ruled out by the reporter: TCP/DNS/port (raw socket connects), TLS in
  general (test.mosquitto.org:8886 works), credentials, and certificate
  verification (`allowUnauthorized`).
- The same broker works from openHAB / Home Assistant.

## What the callback value means (flua models the same contract)

`src/flua/lua/mqtt.lua` mirrors the HC3: the connect callback's argument
is the **client's own error code** (`0` = success) — it reports the
client's transport attempt, *not* the broker's CONNACK. Broker-level
rejections arrive separately as the `connected` event with
`returnCode` 1–5. So a nonzero code like `0xA00042E` means the connection
died at the transport/TLS level **before any CONNACK was processed** —
the broker never accepted the client (or the client never got there).

## Diagnosis

With TCP, generic TLS, credentials, and verification all ruled out, what
remains is the handshake surface itself: modern app-facing brokers are
typically fronted by infrastructure that routes on **ALPN** (`mqtt`);
desktop/mobile stacks (Java Paho, Python paho) send it, and the HC3's
embedded TLS stack apparently does not. The broker silently drops the
connection after the handshake — no CONNACK, nothing for the client to
parse — and the HC3 client's own failure reporting for that shape is
missing (one callback, then silence; no `error`/`closed` events).

The HC3 client's `tls` options cover verification, CA, and SNI only —
there is no ALPN knob. The fix is not on the HC3.

## Workaround (and the confirming experiment)

Bridge it: run mosquitto on a local machine that connects to the target
broker (modern TLS/ALPN, correct certs) and exposes a plain local broker
for the HC3. If the HC3 works through the bridge, the ALPN diagnosis is
confirmed — and the bridge is the workaround. REST polling remains the
other path for services that offer it.

## flua's angle

flua cannot change the HC3's TLS stack. What it provides: the client's
MQTT logic can be developed and verified **offline** against a local
broker (the repo's `tests/test_mqtt.py` MiniBroker and the planned
`net.MQTTBroker`, see notes-mqtt-broker.md), with the HC3's exact
callback/event contract modeled — including this "error code, then
silence" failure shape — and the same QA then runs on the HC3 pointed at
the bridge. The debugging happens against a controllable local broker,
not the real service.
