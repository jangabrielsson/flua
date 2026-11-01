--%%name:WeatherManager
--%%type:com.fibaro.genericDevice
--%%description:"Simulates the HC3 weather: change it from the UI or programmatically with fibaro.call."

--%%u:{label='Condition',text='Condition'}
--%%u:{select='condition',text='Condition',options={{type='option',text='unknown',value='unknown'},{type='option',text='clear',value='clear'},{type='option',text='rain',value='rain'},{type='option',text='snow',value='snow'},{type='option',text='storm',value='storm'},{type='option',text='cloudy',value='cloudy'},{type='option',text='partlyCloudy',value='partlyCloudy'},{type='option',text='fog',value='fog'}},onToggled='_setCondition'}
--%%u:{label='l1',text='Temperature'}
--%%u:{slider='temp',text='Temperature',min=-50,max=50,unit='°C',onChanged='_setTemperature'}
--%%u:{label='l2',text='Humidity'}
--%%u:{slider='humidity',text='Humidity',min=0,max=100,unit='%',onChanged='_setHumidity'}
--%%u:{label='l3',text='Wind'}
--%%u:{slider='wind',text='Wind',min=0,max=200,unit='km/h',onChanged='_setWind'}

-- ----------------------------------------------------------------------------
-- Weather simulator: drives PUT /weather (a flua extension) so scenes and
-- other QAs can react to weather changes like on the HC3. Every change emits
-- WeatherChangedEvents on the refreshStates feed.
--
-- Programmatic use (from another QA or the debugger):
--   fibaro.call(<this QA's id>, "setCondition", "rain")
--   fibaro.call(<this QA's id>, "setTemperature", 18.5)
--   fibaro.call(<this QA's id>, "setHumidity", 80)
--   fibaro.call(<this QA's id>, "setWind", 12)
--
-- The condition vocabulary is the HC3 weather template's ("unknown", "clear",
-- "rain", "snow", "storm", "cloudy", "partlyCloudy", "fog") with its codes.
-- ----------------------------------------------------------------------------

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

-- provider-style names -> select vocabulary ("Partly cloudy" -> "partlyCloudy")
local conditionByName = {}
for name, _ in pairs(conditionCodes) do conditionByName[name:lower()] = name end

local function normalizeCondition(condition)
  return conditionByName[tostring(condition or ""):gsub(" ", ""):lower()]
end

-- The fibaro.call-able actions: setCondition/setTemperature/setHumidity/
-- setWind. The UI callbacks below call the same methods, so UI and
-- programmatic changes share one code path.

function QuickApp:setCondition(condition)
  condition = normalizeCondition(condition) or condition
  local code = conditionCodes[condition]
  if not code then
    self:warning("unknown condition: " .. tostring(condition))
    return
  end
  -- WeatherCondition is the provider-style name and WeatherConditionConverted
  -- the HC3 vocabulary; the sim QA is the provider, so it sets both
  api.put("/weather", {
    ConditionCode = code,
    WeatherCondition = condition,
    WeatherConditionConverted = condition,
  })
end

function QuickApp:setTemperature(value)
  value = tonumber(value)
  if value then api.put("/weather", { Temperature = value }) end
end

function QuickApp:setHumidity(value)
  value = tonumber(value)
  if value then api.put("/weather", { Humidity = value }) end
end

function QuickApp:setWind(value)
  value = tonumber(value)
  if value then api.put("/weather", { Wind = value }) end
end

-- UI callbacks: the viewer delivers event.values = {value}

function QuickApp:_setCondition(event)
  self:setCondition(event.values and event.values[1])
end

function QuickApp:_setTemperature(event)
  self:setTemperature(event.values and event.values[1])
end

function QuickApp:_setHumidity(event)
  self:setHumidity(event.values and event.values[1])
end

function QuickApp:_setWind(event)
  self:setWind(event.values and event.values[1])
end

-- Reflect the current weather into the UI (sliders + condition select).
-- Called at start-up and on every WeatherChangedEvent, so the view stays in
-- sync no matter how the weather changed: this QA's UI, fibaro.call, or an
-- external PUT /weather.
function QuickApp:_syncView(weather)
  self:updateView("condition", "selectedItem",
    normalizeCondition(weather.WeatherConditionConverted)
      or normalizeCondition(weather.WeatherCondition)
      or tostring(weather.WeatherCondition))
  self:updateView("temp", "value", tostring(weather.Temperature))
  self:updateView("humidity", "value", tostring(weather.Humidity))
  self:updateView("wind", "value", tostring(weather.Wind))
end

function QuickApp:onInit()
  self:debug("WeatherSimulator ready, id", self.id)
  local weather = api.get("/weather")
  if weather then self:_syncView(weather) end

  local events = RefreshStateSubscriber()
  events:subscribe(
    function(event) return event.type == "WeatherChangedEvent" end,
    function(event)
      local change = event.data and event.data.change
      local value = event.data and event.data.newValue
      if change == "WeatherCondition" or change == "WeatherConditionConverted" then
        local name = normalizeCondition(value) or tostring(value)
        self:updateView("condition", "selectedItem", name)
      elseif change == "Temperature" then
        self:updateView("temp", "value", tostring(value))
      elseif change == "Humidity" then
        self:updateView("humidity", "value", tostring(value))
      elseif change == "Wind" then
        self:updateView("wind", "value", tostring(value))
      end
    end
  )
  events:run()
  -- a QA with no pending work drains; the simulator stays up indefinitely
  setInterval(function() end, 3600000)
end
