---
id: istypeof-vs-type
topic: hc3-api
title: /devices?isTypeOf= follows the inheritance tree; ?type= is exact
pins:
  - tests/test_api.py::test_devices_query_filters
verified: flua 0.1.168, HC3 5.221
---

# /devices?isTypeOf= follows the inheritance tree; ?type= is exact

Two query filters on the device list, easy to confuse:

- `?isTypeOf=com.fibaro.binarySensor` matches the **whole inheritance
  tree** — a `com.fibaro.FGWDS221` (a Fibaro Z-Wave device registered
  under its product type) shows up because it is a binarySensor child.
- `?type=com.fibaro.binarySensor` matches the type **exactly**.

The sim implements both with the same semantics. The QA builder's
device pickers use `isTypeOf` filters, and the recipe manifests' device
`filter` fields are `isTypeOf` base types — that is why a flood sensor
appears for a `binarySensor` filter.
