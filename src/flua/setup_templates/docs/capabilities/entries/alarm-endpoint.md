---
id: alarm-endpoint
topic: sim-world
title: The alarm system — alarmEndpoint, alarmPanel, and /alarms/v1
pins:
  - tests/test_qa.py::test_load_sim_device_alarm_endpoint
verified: flua 0.1.166
---

# The alarm system — alarmEndpoint, alarmPanel, and /alarms/v1

flua simulates the HC3's alarm model with two bundled devices:

- `_FLUA.loadSimDevice("alarmEndpoint")` — serves the `/alarms/v1/*`
  endpoints with the HC3's partition model: built-in partitions,
  deployed `com.fibaro.alarmPartition` QAs (arming dispatches to the
  QA's own `arm` action), and partitions created via
  `POST /alarms/v1/partitions`.
- `_FLUA.loadSimDevice("alarmPanel")` — a control-panel UI over the
  same endpoints: partition select, Arm/Disarm buttons, live state via
  the refreshState feed.

Breaching a partition emits the alarm events; the endpoint tracks
live-state changes (pinned). Scenes and QAs reacting to
`AlarmPartitionBreachedEvent` / `ArmedEvent` get the same feed as on a
real controller.
