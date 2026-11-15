--%%name:Heat when cold
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:heaterId=0      -- the heater's id (com.fibaro.binarySwitch)
--%%var:threshold=10    -- °C below which the heater starts
-- =====================================================================
-- --------------- EOH ---------------
local HEATER
local THRESHOLD

function QuickApp:onInit()
  HEATER = tonumber(self:getVariable("heaterId")) or 0
  THRESHOLD = tonumber(self:getVariable("threshold")) or 10
  if HEATER == 0 then
    self:debug("set heaterId (the heater's id) and restart")
    return
  end
  setInterval(function() self:checkWeather() end, 30000)
end

function QuickApp:checkWeather()
  local weather = api.get("/weather")
  local temperature = weather and tonumber(weather.Temperature)
  if not temperature then return end
  local heater = api.get("/devices/" .. HEATER)
  local on = heater and heater.properties and heater.properties.value == true
  if temperature < THRESHOLD and not on then
    fibaro.call(HEATER, "turnOn")
    self:debug("heater on (" .. temperature .. "°C)")
  elseif temperature >= THRESHOLD + 1 and on then  -- 1°C hysteresis
    fibaro.call(HEATER, "turnOff")
    self:debug("heater off (" .. temperature .. "°C)")
  end
end
