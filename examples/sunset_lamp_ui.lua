--%%name:SunsetLamp
--%%type:com.fibaro.binarySwitch
--%%var:auto=true
--%%var:wattage=60

--%%u:{label="status",text="Automatic mode"}
--%%u:{switch="automatic",text="Automatic",value="true",onReleased="toggleAuto"}
-- --------------- EOH ---------------
-- The tutorial's running project, chapter 05: the lamp gets a custom UI —
-- an "Automatic" switch and a status label — plus quickApp variables.
-- "auto" is a variable (not a property): a QA's properties are fixed by
-- its type's schema, while variables hold state that must survive restarts.
--   .venv/bin/flua --api local --ui 8090 examples/sunset_lamp_ui.lua
-- (docs/tutorial/05-make-it-yours.md)

function QuickApp:onInit()
  self:debug("Sunset lamp ready,", self:getVariable("wattage"), "W")
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

function QuickApp:toggleAuto(e)
  local auto = e.values and e.values[1] == "true"
  self:setVariable("auto", auto)
  self:updateView("status", "text", auto and "Automatic mode" or "Manual mode")
  if auto then self:checkSun() end
end

function QuickApp:checkSun()
  if not self:getVariable("auto") then return end -- manual mode: hands off
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
