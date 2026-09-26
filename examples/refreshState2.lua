--%%name:refresh-state-demo
--%%mode:online
--%%debug:refreshState=true

local events = {}

local function dumpevents()
  local f = io.open("events.log", "w+")
  if not f then return end
  for k,v in pairs(events) do
    f:write(json.encode(v) .. "\n")
  end
  f:close()
end

local subscriber = RefreshStateSubscriber()
subscriber:subscribe(
  function(event) return true end, 
  function(event) 
    if not events[event.type] then
      --print("Received refresh state event:", event.type) 
      events[event.type] = event
      dumpevents()
    end
  end)
print("Starting the refresh state subscriber...")
subscriber:run()

function QuickApp:onInit()
  print("QuickApp initialized")
  setInterval(function() end,1000)
end
