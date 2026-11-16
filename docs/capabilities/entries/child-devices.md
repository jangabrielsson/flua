---
id: child-devices
topic: qa
title: Child devices — createChildDevice and the ownership guards
pins:
  - tests/test_quickapp.py::test_remove_child_device_guards_foreign_children
verified: flua 0.1.166
---

# Child devices — createChildDevice and the ownership guards

A QA can create its own child devices (parent/child trees, the
multi-sensor pattern):

- `self:createChildDevice(options)` / `plugin.createChildDevice` —
  options can carry Lua tables (select options etc.), which cross the
  bridge losslessly.
- Children are owned: `removeChildDevice` only removes *your own*
  children — removing a foreign device is refused (pinned). A parent
  QA can update its child devices' properties through
  `/plugins/updateProperty`.
- The REST inventory stays consistent after removals (pinned), and
  `plugin.getChildDevices` lists the tree.

Child ids come from the same namespaces as every runtime device —
agents should treat parent/child ids as ordinary device ids.
