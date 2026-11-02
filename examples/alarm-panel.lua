--%%name:AlarmPanel
--%%type:com.fibaro.binarySwitch
--%%u:{button="btnArm",text="Arm",onReleased="arm"}
--%%u:{button="btnDisarm",text="Disarm",onReleased="disarm"}
--%%u:{label="lblState",text="disarmed"}
-- The mock alarm panel DEPLOYED AS A QA: its UI is a real device in the
-- sim, and requiring alarm-logic makes its endpoints answer every QA's
-- api.* calls (override routes). Run it alongside consumers:
--   .venv/bin/flua --api local examples/alarm-panel.lua examples/uses-alarm-panel.lua

local listener

function QuickApp:onInit()
  local alarm = require("alarm-logic")
  api.post("/alarms/v1/partitions", {name='Garage'})
  listener()
end

function QuickApp:arm()
  api.post("/alarms/v1/partitions/1/actions/arm")
end

function QuickApp:disarm()
  api.delete("/alarms/v1/partitions/1/actions/disarm")
end

local Events = {
  AlarmPartitionArmedEvent = function(d) 
    local id = d.partitionId
    local armed = d.armed
    print("Partion", id, "armed:", armed)
  end,
  AlarmPartitionBreachedEvent = function(d) 
    local id = d.partitionId
    local breached = d.breached
    print("Partion", id, "breached:", breached)
  end,
  AlarmPartitionModifiedEvent = function(d)
    local id = d.partitionId
    print("Partion", id, "modified")
  end,
  HomeArmStateChangedEvent = function(d) 
    local newValue = d.newValue
    print("Home armed state changed:", newValue)
  end,
  HomeDisarmStateChangedEvent = function(d) 
    local newValue = d.newValue
    print("Home disarmed state changed:", newValue)
  end,
  HomeBreachedEvent = function(d) 
    local breached = d.breached
    print("Home breached state changed:", breached)
  end,
}

function listener()
  local subscriber = RefreshStateSubscriber()
  subscriber:subscribe(
  function(event) return true end, 
  function(event) 
    if Events[event.type] then
      Events[event.type](event.data)
    end
  end)
  subscriber:run()
end
