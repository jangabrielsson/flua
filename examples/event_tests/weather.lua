--%%name:Weather
--%%type:com.fibaro.weather

-- Weather type have no actions to handle
-- To update temperature, update property "Temperature" with floating point number, supported units: "C" - Celsius, "F" - Fahrenheit
-- To update humidity, update property "Humidity" with floating point number
-- To update wind speed, update property "Wind" with floating point number
-- Eg. self:updateProperty("Temperature", { value= 18.12, unit= "C" })
-- To update weather condition, update properties "ConditionCode" and "WeatherCondition" or use method QuickApp:setCondition
-- Eg. self:setCondition("clear")

-- Posible conditions: "unknown", "clear", "rain", "snow", "storm", "cloudy", "partlyCloudy", "fog"
function QuickApp:setCondition(condition)
  local conditionCodes = { 
    unknown = 3200,
    clear = 32,
    rain = 40,
    snow = 38,
    storm = 4,
    cloudy = 30,
    partlyCloudy = 30,
    fog = 20,
  }
  
  local conditionCode = conditionCodes[condition]
  
  if conditionCode then
    _FLUA.postRefreshEvent({type='WeatherChangedEvent',data={change='WeatherCondition', newValue=condition, oldValue=self.properties.WeatherCondition}})
    _FLUA.postRefreshEvent({type='WeatherChangedEvent',data={change='ConditionCode', newValue=conditionCode, oldValue=self.properties.ConditionCode}})
    self:updateProperty("ConditionCode", conditionCode)
    self:updateProperty("WeatherCondition", condition)
  end
end

function QuickApp:setTemperature(value, unit)
  _FLUA.postRefreshEvent({type='WeatherChangedEvent',data={change='Temperature', newValue=value, oldValue=self.properties.Temperature}})
  self:updateProperty("Temperature", value)
end

function QuickApp:setHumidity(value)
  _FLUA.postRefreshEvent({type='WeatherChangedEvent',data={change='Humidity', newValue=value, oldValue=self.properties.Humidity}})
  self:updateProperty("Humidity", value)
end

function QuickApp:setWind(value)
  _FLUA.postRefreshEvent({type='WeatherChangedEvent',data={change='Wind', newValue=value, oldValue=self.properties.Wind}})
  self:updateProperty("Wind", value)
end

function QuickApp:onInit()
  self:debug("Initialized weather")
end 