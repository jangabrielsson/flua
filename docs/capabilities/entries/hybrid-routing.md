---
id: hybrid-routing
topic: hc3-api
title: Hybrid routing — the sim answers first, unknown ids forward to the HC3
pins:
  - tests/test_hc3.py::test_hybrid_routing_local_sim_and_remote_hc3
  - tests/test_api.py::test_readonly_mode_refuses_remote_writes_at_the_gate
verified: flua 0.1.169
---

# Hybrid routing — the sim answers first, unknown ids forward to the HC3

How a QA's `api.*` call finds its data in online mode:

- The sim handles what it owns (flua QAs, sim devices, sim variables);
  a 404 for an entity the sim doesn't own falls back to the real HC3.
  `/devices` lists the *union*, sim winning id clashes.
- `--%%mode:offline` on a QA pins it to the sim (its remote hook is
  None — no fallback, ever). `--%%mode:readonly[+call]` keeps reads
  through the hybrid dispatch but refuses mutating remote verbs with
  403 before they reach the controller.
- `api.hc3.*` (and `fibaro.callhc3`) bypass the hybrid dispatch —
  always the real HC3 online, the sim stands in offline.
- Variables endpoints the HC3 refuses to external REST callers go
  through the FluaHelper bridge (controller-local context), not the
  plain REST transport.
- The remote REST rides `X-Fibaro-Version: 2` like the web UI.
