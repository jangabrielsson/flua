---
id: proxy-mode
topic: deploy
title: Proxy mode — the QA runs on the HC3 with a sim shadow of the same id
pins:
  - tests/test_proxy.py::test_proxy_fresh_deploy_reuses_id_and_connects
verified: flua 0.1.166
---

# Proxy mode — the QA runs on the HC3 with a sim shadow of the same id

`--%%mode:proxy` deploys a mirror QA onto the HC3: the emulated QA runs
under the proxy's HC3 id, so the sim shadow and the controller device
are the *same* id.

- A fresh deploy reuses the existing proxy device id instead of
  recreating it (pinned), and the proxy QA shares state with the
  controller — it is not a second device in `/devices`.
- The HC3 owns the proxy's state: changes mirror through the poll, and
  the proxy never emits local refresh events (exactly-once — the HC3
  already recorded them).
- `--%%mode:proxy,noUI` connects without clobbering the proxy's UI
  (developers who edit it in the HC3's editor).
- Proxy mode is online-only; offline it degrades to a plain QA with a
  warning. Variables of proxy devices live on the controller and go
  through the FluaHelper bridge.
