--%%name:Motion lights
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:motionId=0        -- the motion sensor's id (com.fibaro.motionSensor)
--%%var:lightId=0         -- the light's id (com.fibaro.binarySwitch)
--%%var:minutes=5         -- how long the light stays on after motion
--%%u:{slider='minutesSlider',text='On for (minutes)',min=1,max=120,unit='min',onChanged='_setMinutes'}
-- =====================================================================
-- --------------- EOH ---------------
local MOTION
local LIGHT
local MINUTES

function QuickApp:onInit()
  MOTION = tonumber(self:getVariable("motionId")) or 0
  LIGHT = tonumber(self:getVariable("lightId")) or 0
  MINUTES = tonumber(self:getVariable("minutes")) or 5
  self:updateView("minutesSlider", "value", tostring(MINUTES))
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
    fibaro.call(LIGHT, "turnOn")
    if self._offTimer then clearTimeout(self._offTimer) end
    self._offTimer = setTimeout(function()
      fibaro.call(LIGHT, "turnOff")
    end, MINUTES * 60 * 1000)
  end
end

-- UI: the slider changes how long the light stays on — it applies from
-- the next motion (a pending off-timer keeps its old duration)
function QuickApp:_setMinutes(event)
  local v = tonumber(event.values and event.values[1])
  if not v then return end
  MINUTES = v
  self:setVariable("minutes", v)
  self:updateView("minutesSlider", "value", tostring(v))
end
