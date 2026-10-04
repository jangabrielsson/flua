--%%name:SunsetLamp
--%%type:com.fibaro.binarySwitch
-- The tutorial's running project: a lamp QA with turnOn/turnOff actions.
-- Run with:  .venv/bin/flua --ui --api local examples/sunset_lamp.lua
-- and click the buttons in the viewer (docs/tutorial/03-qa-anatomy.md).

function QuickApp:onInit()
  self:debug("Sunset lamp ready")
end

function QuickApp:turnOn()
  self:updateProperty("value", true)
  print("Lamp on")
end

function QuickApp:turnOff()
  self:updateProperty("value", false)
  print("Lamp off")
end
