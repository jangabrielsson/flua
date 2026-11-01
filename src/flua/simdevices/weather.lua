--%%name:Weather
--%%type:com.fibaro.weather
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "setCondition", "rain")  -- unknown/clear/rain/snow/storm/cloudy/partlyCloudy/fog
--   fibaro.call(id, "setTemperature" / "setHumidity" / "setWind", value)

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
end
local conditionCodes = {
  unknown = 3200, clear = 32, rain = 40, snow = 38,
  storm = 4, cloudy = 30, partlyCloudy = 30, fog = 20,
}

-- the QA's own weather properties (for the shared /weather endpoint
-- simulator, see examples/sim_endpoints/weather.lua)

function QuickApp:setCondition(condition)
  local code = conditionCodes[condition]
  if not code then
    self:warning("unknown condition: " .. tostring(condition))
    return
  end
  self:updateProperty("ConditionCode", code)
  self:updateProperty("WeatherCondition", condition)
end

function QuickApp:setTemperature(value)
  value = tonumber(value)
  if value then self:updateProperty("Temperature", value) end
end

function QuickApp:setHumidity(value)
  value = tonumber(value)
  if value then self:updateProperty("Humidity", value) end
end

function QuickApp:setWind(value)
  value = tonumber(value)
  if value then self:updateProperty("Wind", value) end
end

