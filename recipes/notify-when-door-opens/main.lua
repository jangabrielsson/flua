--%%name:Door open notification
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:doorId=0          -- the door sensor's device id (com.fibaro.doorSensor)
--%%var:message=The door opened
-- =====================================================================
-- --------------- EOH ---------------
local DOOR
local MESSAGE

function QuickApp:onInit()
  DOOR = tonumber(self:getVariable("doorId")) or 0
  MESSAGE = self:getVariable("message") or 'The door opened'
  if DOOR == 0 then
    self:debug("set doorId (the door sensor's id) and restart")
    return
  end
  self._sent = false
  setInterval(function() self:checkDoor() end, 5000)
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
