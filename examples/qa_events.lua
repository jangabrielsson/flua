--%%name:qa_events
--%%type:com.fibaro.binarySwitch
--%%mode:offline

QATracker = {}
class 'QATracker'
function QATracker:__init()
  self.qas = {}
  local qas = api.get("/devices?interface=quickApp")
  for _,qa in ipairs(qas) do
    self.qas[qa.id] = true
  end
  self.refresh = RefreshStateSubscriber()
  self.refresh:subscribe(function(event) 
    if self.log then print("RefreshEvent:",json.encode(event)) end
    return true 
  end,function(event) 
    if self[event.type] then self[event.type](self,event) end
  end)
  self.refresh:run()
end

function QATracker:DeviceCreatedEvent(event)
  self.qas[event.data.id] = true
  print(event.data.id,"created")
end

function QATracker:DeviceRemovedEvent(event)
  self.qas[event.data.id] = nil
  print(event.data.id,"removed")
end

function QuickApp:onInit()
  local watcher = QATracker()
  local id = _FLUA.loadQAfromFile("examples/event_tests/weather.lua")
  print(id)
  api.delete("/devices/" .. id)
end