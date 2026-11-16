---
id: qa-ui-elements
topic: ui
title: QA UI — --%%u rows, updateView, and how taps arrive
pins:
  - tests/test_ui_server.py::test_update_view_visible_over_http
  - tests/test_qa.py::test_sim_device_sensor_ui
verified: flua 0.1.168
---

# QA UI — --%%u rows, updateView, and how taps arrive

A QA declares its UI with `--%%u` rows in the header (repeatable, order
kept; they travel in the .fqa as uiCallbacks/viewLayout):

```
--%%u:{slider='thresholdSlider',text='Start above (%)',min=20,max=100,unit='%',onChanged='_setThreshold'}
--%%u:{{button='btnBreach',text='Breach / on',onReleased='breach'},{button='btnClear',text='Clear / off',onReleased='clearBreach'}}
```

- A callback name (`onReleased='breach'`) routes the tap to
  `QuickApp:breach(event)`; `onChanged` handlers read the value from
  `event.values[1]` (a string — `tonumber` it).
- `self:updateView(elm, prop, value)` patches live state at runtime;
  boot-sync the slider from the variable and write the variable back in
  the handler so the UI and the logic stay one state.
- The viewer merges `updateView` state over the layout
  (`/plugins/getView` serves the merged tree); `--%%useUiView:true`
  opts into the new uiView component format.
- `self:UIAction(eventType, elementName, arg)` fires a UI event
  programmatically (test code, dry-runs).
