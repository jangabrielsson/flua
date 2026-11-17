--%%name:Humidity fan
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:humidityId=0      -- the humidity sensor's id (com.fibaro.humiditySensor)
--%%var:fanId=0           -- the fan/switch's id (com.fibaro.binarySwitch)
--%%var:threshold=65      -- humidity % that starts the fan
--%%u:{slider='thresholdSlider',text='Start fan above (%)',min=20,max=100,unit='%',onChanged='_setThreshold'}
-- =====================================================================
-- --------------- EOH ---------------
local HUMIDITY
local FAN
local THRESHOLD

function QuickApp:onInit()
  HUMIDITY = tonumber(self:getVariable("humidityId")) or 0
  FAN = tonumber(self:getVariable("fanId")) or 0
  THRESHOLD = tonumber(self:getVariable("threshold")) or 65
  self:updateView("thresholdSlider", "value", tostring(THRESHOLD))
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
    self:debug("fan on (humidity " .. humidity .. "%)")
  elseif humidity <= THRESHOLD - 5 and on then  -- 5% hysteresis
    fibaro.call(FAN, "turnOff")
    self:debug("fan off (humidity " .. humidity .. "%)")
  end
end

-- UI: the slider changes the threshold the QA uses right away
function QuickApp:_setThreshold(event)
  local v = tonumber(event.values and event.values[1])
  if not v then return end
  THRESHOLD = v
  self:setVariable("threshold", v)
  self:updateView("thresholdSlider", "value", tostring(v))
end
