--%%name:Leak alert
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:floodId=0         -- the flood sensor's id (com.fibaro.floodSensor)
--%%var:sirenId=0         -- optional siren/switch to turn on (0 = none)
-- =====================================================================
-- --------------- EOH ---------------
local FLOOD
local SIREN

function QuickApp:onInit()
  FLOOD = tonumber(self:getVariable("floodId")) or 0
  SIREN = tonumber(self:getVariable("sirenId")) or 0
  if FLOOD == 0 then
    self:debug("set floodId (the flood sensor's id) and restart")
    return
  end
  self._wet = false
  -- react to the flood sensor instantly: the refreshStates event feed
  -- (RefreshStateSubscriber is the HC3 mechanism; flua simulates it)
  local events = RefreshStateSubscriber()
  events:subscribe(
    function(event)
      return event.type == "DevicePropertyUpdatedEvent"
        and event.data and event.data.id == FLOOD
        and event.data.property == "value"
    end,
    function() self:checkFlood() end
  )
  events:run()
  self:checkFlood()  -- the state at boot (the floor may already be wet)
  -- a slow reconcile poll: self-heals a missed event, and keeps the QA
  -- alive in flua (a QA with no pending work drains)
  setInterval(function() self:checkFlood() end, 300000)
end

function QuickApp:checkFlood()
  local flood = api.get("/devices/" .. FLOOD)
  local wet = flood and flood.properties and flood.properties.value == true
  if wet and not self._wet then  -- dry -> wet: push once, sound the siren
    self._wet = true
    fibaro.call(2, "sendPush", "Water detected!")
    if SIREN > 0 then fibaro.call(SIREN, "turnOn") end
    self:debug("water detected")
  elseif not wet and self._wet then  -- wet -> dry: silence the siren
    self._wet = false
    if SIREN > 0 then fibaro.call(SIREN, "turnOff") end
    self:debug("water cleared")
  end
end
