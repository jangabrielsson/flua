--%%name:Humidity fan
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:humidityId=0      -- the humidity sensor's id (com.fibaro.humiditySensor)
--%%var:fanId=0           -- the fan/switch's id (com.fibaro.binarySwitch)
--%%var:threshold=65      -- humidity % that starts the fan
-- =====================================================================
-- --------------- EOH ---------------
local HUMIDITY
local FAN
local THRESHOLD

function QuickApp:onInit()
  HUMIDITY = tonumber(self:getVariable("humidityId")) or 0
  FAN = tonumber(self:getVariable("fanId")) or 0
  THRESHOLD = tonumber(self:getVariable("threshold")) or 65
  if HUMIDITY == 0 or FAN == 0 then
    self:debug("set humidityId and fanId, then restart")
    return
  end
  setInterval(function() self:checkHumidity() end, 30000)
end

function QuickApp:checkHumidity()
  local sensor = api.get("/devices/" .. HUMIDITY)
  local humidity = sensor and sensor.properties and sensor.properties.value
  if not humidity then return end
  local fan = api.get("/devices/" .. FAN)
  local on = fan and fan.properties and fan.properties.value == true
  if humidity > THRESHOLD and not on then
    fibaro.call(FAN, "turnOn")
  elseif humidity <= THRESHOLD - 5 and on then  -- 5% hysteresis
    fibaro.call(FAN, "turnOff")
  end
end
