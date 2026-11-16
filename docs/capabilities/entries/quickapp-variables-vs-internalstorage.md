---
id: quickapp-variables-vs-internalstorage
topic: packaging
title: quickAppVariables travel with downloads; internalStorage is fresh-install state
pins:
  - tests/test_api.py::test_qa_uses_api_offline
verified: flua 0.1.169
---

# quickAppVariables travel with downloads; internalStorage is fresh-install state

Two variable stores, one crucial difference:

- **quickAppVariables** (`self:getVariable`/`setVariable`, `--%%var`
  seeds) are part of the device — they travel when someone downloads
  the QA, so they survive re-uploads and re-distribution.
- **internalStorage** (`self:internalStorageSet`/`Get`, backed by
  `/plugins/<id>/variables`) is *not* saved when people download QAs —
  it is per-installation state.

That asymmetry is a feature: a QA that must run once per fresh install
(first-run setup, icon installation) keeps its done-flag in
internalStorage — a downloaded copy starts fresh, while quickAppVariables
carry the user's configuration. The sim implements both; a QA relying
on the distinction behaves the same on the controller.
