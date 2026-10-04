--%%name:trigger

-- Example how a QA can react on another QA changing state.

local doorDevice = _FLUA.loadQAfromString([[
--%%name:Door
--%%type:com.fibaro.doorSensor

function QuickApp:onInit()
  print("Door QA initialized")
end

function QuickApp:breach()
  print("Door breached")
  self:updateProperty("value", true)
end

function QuickApp:safe()
  print("Door safe")
  self:updateProperty("value", false)
end
]])

function QuickApp:watchSensor(id)
  local subscriber = RefreshStateSubscriber()
  subscriber:subscribe(
  function(event) return true end, 
  function(event) 
    if event.data.id == id and event.data.property == "value" then
      self:sensorChangedState(event.data.newValue)
    end
  end)
  print("Starting the refresh state subscriber...")
  subscriber:run()
end

function QuickApp:onInit()
  print("QuickApp initialized")
  self:watchSensor(doorDevice)
  setTimeout(function() fibaro.call(doorDevice, "breach") end, 1000)  -- Simulate the door being breached after 1 second
  setTimeout(function() fibaro.call(doorDevice, "safe") end, 3000)  -- Simulate the door being safe after 3 seconds
end

function QuickApp:sensorChangedState(state)
  print("Sensor changed state:", state)
end
