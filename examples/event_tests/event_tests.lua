--%%name:EventTest
--%%type:com.fibaro.multilevelSwitch
--%%mode:online
--%%file:$event_mgr.lua,event

local EM = fibaro.EventMgr()
--EM.log = true
local alarmPartition,err = _FLUA.loadQAfromFile("examples/event_tests/partition.lua")
local weather,err = _FLUA.loadQAfromFile("examples/event_tests/weather.lua")

EM:addHandler({type='device', property='value'},function(event)
  print(json.encode(event))
end)

EM:addHandler({type='alarm'},function(event)
  print(json.encode(event))
end)

EM:addHandler({type='weather'},function(event)
  print("Weather",event.property, event.value, event.old)
end)

EM:addHandler({type='global-variable'},function(event)
  print(json.encode(event))
end)

local t = 1000
function QuickApp:test(fun)
  setTimeout(fun, t)
  t = t + 500
end

function QuickApp:onInit()
  self:test(function() self:updateProperty('value',55) end)
  self:test(function() fibaro.call(alarmPartition, "arm") end)
  self:test(function() fibaro.call(alarmPartition, "disarm") end)

  self:test(function() fibaro.call(weather, "setCondition", "clear") end)
  self:test(function() fibaro.call(weather, "setTemperature", 18.12, "C") end)
  self:test(function() fibaro.call(weather, "setHumidity", 55) end)
  self:test(function() fibaro.call(weather, "setWind", 10) end)

  self:test(function() api.post("/globalVariables",{name="TestVariable", value="123"}) end) -- create global
  self:test(function() fibaro.setGlobalVariable("TestVariable", "321") end) -- update global
end
