--%%name:SunsetLamp
--%%type:com.fibaro.binarySwitch
-- --------------- EOH ---------------
-- The tutorial's running project, chapter 04: the lamp checks the sun once
-- a minute and switches itself on at sunset, off again in the morning.
--   .venv/bin/flua --api local --start '2026/10/4 18:30:00' examples/sunset_lamp_auto.lua
-- (docs/tutorial/04-the-house-comes-alive.md)

function QuickApp:onInit()
  self:debug("Sunset lamp ready")
  self:checkSun()
  setInterval(function() self:checkSun() end, 60 * 1000) -- once a minute
end

function QuickApp:turnOn()
  self:updateProperty("value", true)
  print("Lamp on")
end

function QuickApp:turnOff()
  self:updateProperty("value", false)
  print("Lamp off")
end

function QuickApp:checkSun()
  local now = os.date("*t")
  local h, m = fibaro.getValue(1, "sunsetHour"):match("(%d+):(%d+)")
  local sunsetMin = tonumber(h) * 60 + tonumber(m)
  local nowMin = now.hour * 60 + now.min
  if nowMin >= sunsetMin and not self.properties.value then
    self:turnOn()
  elseif nowMin < sunsetMin and self.properties.value then
    self:turnOff()
  end
end
