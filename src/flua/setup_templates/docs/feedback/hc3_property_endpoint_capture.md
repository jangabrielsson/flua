# Live-HC3 capture: `GET /devices/{id}/properties/{name}`

Captured 2026-10-31 against the author's HC3 (read-only; no mutations) to
settle the GPTAstra feedback finding 5: does the HC3 return the raw
property value or an envelope? **The envelope.**

| Case | Request | Status | Body |
|---|---|---|---|
| boolean false | `/devices/1/properties/dead` | 200 | `{"value": false, "modified": 1793263194}` |
| zero | `/devices/1/properties/UIMessageSendTime` | 200 | `{"value": 0, "modified": 1793263194}` |
| empty string | `/devices/1/properties/liliOffCommand` | 200 | `{"value": "", "modified": 1793263194}` |
| object | `/devices/2/properties/buiSettings` | 200 | `{"value": {}, "modified": 1793263194}` |
| missing property | `/devices/1/properties/__flua_capture_missing__` | 404 | `null` |

- `modified` is the epoch-seconds last-change time (all sampled properties
  of one device shared it in this capture — the HC3 appears to track it at
  device granularity).
- flua's sim now mirrors this contract: `device_property_get` wraps every
  value (scalars, objects, the computed device-1 sun times) as
  `{value, modified}`, 404/null for missing. The sim's `modified` starts
  at device registration/first-read time and advances on every property
  change (`record_property_event`).
- Pinned by `tests/test_api.py::test_device_property_get` and
  `test_device_property_put`.
- `plugin.getProperty(id, name)` is unaffected: it reads the full-device
  route (`/devices/{id}`) and returns the raw value, like the HC3's Lua
  API.
