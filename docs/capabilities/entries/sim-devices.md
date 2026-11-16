---
id: sim-devices
topic: sim-world
title: The bundled sim devices — drive a world without an HC3
pins:
  - tests/test_qa.py::test_sim_device_sensor_ui
  - tests/test_qa.py::test_load_sim_device_bundled
verified: flua 0.1.168
---

# The bundled sim devices — drive a world without an HC3

`src/flua/simdevices/*.lua` ship in the wheel and load by bare name:

```lua
local motion = _FLUA.loadSimDevice("motionSensor")
fibaro.call(motion, "breach")          -- value = true
local temp = _FLUA.loadSimDevice("temperatureSensor",
  {"name:Hall temp", "property:value=21.5", "property:unit=C"})
```

- The directive table (second argument) presets properties, renames, or
  overrides the header — one bundled device becomes any number of
  distinct devices.
- Value sensors take `setValue(value, unit?)`; breach sensors
  `setValue(bool)/breach/clearBreach` (the sensor's `value` IS the
  breach state); switches `turnOn/turnOff`; `weatherMgr` drives
  `PUT /weather` with sliders.
- Sensors carry a UI in the web view: binary ones Breach/Clear buttons,
  multilevel ones sliders over their real range — tap them and reacting
  QAs fire, so `--ui` doubles as a test bench. Boot value is a number
  (0), never the skeleton's empty string (Lua truthiness would make
  `value > threshold` crash).
- Sim devices keep themselves alive (`_FLUA.keepAlive()`) and are the
  builder's offline pickers (`sim:` picks).
