--%%name:refresh-state-demo

local subscriber = RefreshStateSubscriber()
subscriber:subscribe(
  function(event) return true end, 
  function(event) 
    print("Received refresh state event:", json.encode(event)) 
  end)
print("Starting the refresh state subscriber...")
subscriber:run()

-- Stop the subscriber after some time (for demonstration purposes)
setTimeout(function()
  print("Stopping the refresh state subscriber...")
  subscriber:stop()
end, 10000)  -- Stop after 10 seconds

function QuickApp:onInit()
  print("QuickApp initialized")
  setTimeout(function()
    self:toggle()
  end, 1000)  -- Delay for 1 second
end

function QuickApp:toggle()
  print("QuickApp toggled")
  local v = fibaro.getValue(self.id, "value")
  if type(v) == 'number' then v = v ~= 0 end
  print("Current value:", v)
  v = not v
  self:updateProperty("value",v)
end