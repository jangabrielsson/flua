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
  setInterval(function() self:checkFlood() end, 5000)
end

function QuickApp:checkFlood()
  local flood = api.get("/devices/" .. FLOOD)
  if flood and flood.properties and flood.properties.value == true then
    fibaro.call(2, "sendPush", "Water detected!")
    if SIREN > 0 then api.post("/devices/" .. SIREN .. "/action/turnOn") end
    self:debug("water detected")
  end
end
