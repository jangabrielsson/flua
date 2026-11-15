--%%name:Door open notification
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:doorId=0          -- the door sensor's device id (com.fibaro.doorSensor)
--%%var:message="The door opened"
-- =====================================================================
-- --------------- EOH ---------------
local DOOR
local MESSAGE

function QuickApp:onInit()
  DOOR = tonumber(self:getVariable("doorId")) or 0
  MESSAGE = self:getVariable("message") or "The door opened"
  if DOOR == 0 then
    self:debug("set doorId (the door sensor's id) and restart")
    return
  end
  self._sent = false
  -- react to the door sensor instantly: the refreshStates event feed
  -- (RefreshStateSubscriber is the HC3 mechanism; flua simulates it)
  local events = RefreshStateSubscriber()
  events:subscribe(
    function(event)
      return event.type == "DevicePropertyUpdatedEvent"
        and event.data and event.data.id == DOOR
        and event.data.property == "value"
    end,
    function() self:checkDoor() end
  )
  events:run()
  self:checkDoor()  -- the state at boot (the door may already be open)
  -- a slow reconcile poll: self-heals a missed event, and keeps the QA
  -- alive in flua (a QA with no pending work drains)
  setInterval(function() self:checkDoor() end, 300000)
end

function QuickApp:checkDoor()
  local door = api.get("/devices/" .. DOOR)
  local open = door and door.properties and door.properties.value == true
  if open and not self._sent then
    self._sent = true
    self:notify(MESSAGE)
  elseif not open and self._sent then
    self._sent = false  -- arm it again for the next opening
  end
end

function QuickApp:notify(text)
  fibaro.call(2, "sendPush", text)  -- device 2 = the controller's push channel
  self:debug("push: " .. text)
end
