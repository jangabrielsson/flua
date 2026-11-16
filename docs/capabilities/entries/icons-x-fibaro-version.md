---
id: icons-x-fibaro-version
topic: hc3-api
title: /icons is shaped by the X-Fibaro-Version header
pins:
  - tests/test_hc3.py::test_hc3_remote_sends_fibaro_version_header
verified: flua 0.1.167, HC3 5.221
---

# /icons is shaped by the X-Fibaro-Version header

flua's remote REST rides `X-Fibaro-Version: 2` (the web UI's shape), and
the HC3's `/icons` answers **differently per version**:

- **v1**: the full icon library — `{<iconId>: {name, stateMaps, ...}}`.
- **v2**: a per-type table (devices/rooms/scenes), a subset — what the
  web UI uses.

Gotchas, all live-verified:

- Never combine query params with v2 on `/icons` — the controller
  hangs (the swagger UI does not).
- A QA's `api.get("/icons")` returns the **v2** shape; the icon-manager
  tool uses v1 explicitly.
- To read the v1 library from QA code, use a raw `net.HTTPClient` call
  with the `X-Fibaro-Version: 1` header.

Custom icon sets show up under v2 as `User<id>` entries whose
`deviceType` is the *registered* type (e.g. `com.fibaro.FGWDS221`), not
the base type — match children with `isTypeOf`, see
`istypeof-vs-type`.
