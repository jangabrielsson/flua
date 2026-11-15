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
  -- react to the motion sensor instantly: the refreshStates event feed
  -- (RefreshStateSubscriber is the HC3 mechanism; flua simulates it)
  local events = RefreshStateSubscriber()
  events:subscribe(
    function(event)
      return event.type == "DevicePropertyUpdatedEvent"
        and event.data and event.data.id == MOTION
        and event.data.property == "value"
    end,
    function() self:checkMotion() end
  )
  events:run()
  self:checkMotion()  -- the state at boot (the sensor may already be breached)
  -- a slow reconcile poll: self-heals a missed event, and keeps the QA
  -- alive in flua (a QA with no pending work drains)
  setInterval(function() self:checkMotion() end, 300000)
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
