--%%name:Motion lights
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:motionId=0        -- the motion sensor's id (com.fibaro.motionSensor)
--%%var:lightId=0         -- the light's id (com.fibaro.binarySwitch)
--%%var:minutes=5         -- how long the light stays on after motion
-- =====================================================================
-- --------------- EOH ---------------
local MOTION = tonumber(self:getVariable("motionId")) or 0
local LIGHT = tonumber(self:getVariable("lightId")) or 0
local MINUTES = tonumber(self:getVariable("minutes")) or 5

function QuickApp:onInit()
  if MOTION == 0 or LIGHT == 0 then
    self:debug("set motionId and lightId, then restart")
    return
  end
  self._offTimer = nil
  setInterval(function() self:checkMotion() end, 3000)
end

function QuickApp:checkMotion()
  local motion = api.get("/devices/" .. MOTION)
  if motion and motion.properties and motion.properties.value == true then
    api.post("/devices/" .. LIGHT .. "/action/turnOn")
    if self._offTimer then clearTimeout(self._offTimer) end
    self._offTimer = setTimeout(function()
      api.post("/devices/" .. LIGHT .. "/action/turnOff")
    end, MINUTES * 60 * 1000)
  end
end
