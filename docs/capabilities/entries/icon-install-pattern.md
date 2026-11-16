---
id: icon-install-pattern
topic: patterns
title: First-run detection — internalStorage flags vs quickAppVariables
pins:
  - tests/test_hc3.py::test_example_icon_install_uploads_on_fresh_install
verified: flua 0.1.170
---

# First-run detection — internalStorage flags vs quickAppVariables

`examples/iconInstall.lua` is the living pattern for "do this once after
a fresh install":

- The done-flag lives in **internalStorage** (`plugins/<id>/variables`)
  — *not* saved when people download QAs — while **quickAppVariables
  travel** with the download. A downloaded copy starts fresh; the
  user's configuration carries over. See
  `quickapp-variables-vs-internalstorage`.
- First start (flag missing): check the icon set, install it via the
  QuickApp icon APIs, set `defaultIcon`, store the flag. Restarts
  skip the work.
- The icon files sit beside the QA in the repo and are fetched from
  the raw GitHub channel — the same channel the recipe library uses.

Pinned end to end against the mock HC3: fresh install uploads, a
restart with the flag skips, a stale flag re-installs.
