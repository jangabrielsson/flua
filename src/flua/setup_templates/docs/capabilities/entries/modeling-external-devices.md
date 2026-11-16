---
id: modeling-external-devices
topic: sim-world
title: Model the external device as a sim QA speaking the real protocol
pins:
  - tests/test_modbus_mock.py::test_solaredge_mock_serves_both_wire_bases
  - tests/test_modbus_mock.py::test_modbus_server_write_functions_round_trip
verified: flua 0.1.169
---

# Model the external device as a sim QA speaking the real protocol

For integrations, the *far side* should be a QA in the sim — not a
Python fake:

- `examples/Modbus Server/` — a Modbus server in Lua (write functions
  round-trip, pinned) plus a Solaredge device and its mock that serves
  **both wire bases** (client and buttons) — the complete
  device+mock pair in one folder.
- The bundled sim devices are the same idea for house devices
  (`weatherMgr` drives `PUT /weather`, `alarmEndpoint` serves
  `/alarms/v1`) — see `sim-devices`.
- The device QA holds its state in properties and emits
  `DevicePropertyUpdatedEvent`s, so the QA under test reacts through
  the normal event feed — no special test hooks.

Result: the integration runs offline exactly as it would against the
real device, and the device model doubles as the fixture in the
pinning tests. Write the model once, use it everywhere.
