---
id: builder-tool
topic: tooling
title: The QA builder — recipes to QAs, parked as a PoC
pins:
  - tests/test_builder.py::test_builder_serves_the_page_and_index
verified: flua 0.1.170
---

# The QA builder — recipes to QAs, parked as a PoC

`flua --tool build` serves a browser page that turns the recipe library
into finished QAs: pick a recipe (categories, live from GitHub — one
merge, no release), pick the devices (HC3 pickers filtered by
`isTypeOf`, or simulated-device picks offline), generate → simulate →
view UI → upload. The generated code is editable Lua the user owns.

- Simulate runs the QA in the sim on a 600x clock; View UI serves the
  HC3-style viewer with the picked devices seeded as sim devices.
- Every recipe carries a declarative verify scenario
  (`recipe-verify-scenarios`); `build --verify-all` is the CI gate on
  template changes.
- Status: a **parked proof of concept** — ADR 0015 delimits it against
  the no-wizard decision (ADR 0013): it is a tool on top of flua, and
  any page capability must arrive as a CLI/JSON surface first.

The recipe manifest schema (params/filters/categories/simDevices/verify)
is documented in USAGE.md; the recipe library itself lives in
`recipes/`.
