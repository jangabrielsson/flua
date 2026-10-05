--%%name:trigger-lamp
--%%type:com.fibaro.binarySwitch
-- Multi-QA debugging demo (docs/tutorial/10-multi-qa-debugging.md): the
-- lamp answers the sensor's "toggle" action.
-- Run with:
--   .venv/bin/flua --api local examples/trigger_sensor.lua examples/trigger_lamp.lua

function QuickApp:onInit()
  self:debug("lamp online")
end

function QuickApp:toggle()
  local on = not self.properties.value
  self:updateProperty("value", on)
  print("lamp now", on and "ON" or "OFF")
end
