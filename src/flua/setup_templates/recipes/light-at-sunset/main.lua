--%%name:Light at sunset
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:deviceId=0        -- the light's device id (com.fibaro.binarySwitch)
--%%var:offset=-30        -- minutes before (-) / after (+) sunset
--%%u:{slider='offsetSlider',text='Minutes around sunset',min=-120,max=120,unit='min',onChanged='_setOffset'}
-- =====================================================================
-- --------------- EOH ---------------
local LIGHT
local OFFSET

function QuickApp:onInit()
  LIGHT = tonumber(self:getVariable("deviceId")) or 0
  OFFSET = tonumber(self:getVariable("offset")) or -30
  self:updateView("offsetSlider", "value", tostring(OFFSET))
  if LIGHT == 0 then
    self:debug("set deviceId (the light's id) and restart")
    return
  end
  self:scheduleNext()
  setInterval(function() self:scheduleNext() end, 3600 * 1000)  -- re-check daily
end

function QuickApp:scheduleNext()
  local hub = api.get("/devices/1")
  local sunset = hub and hub.properties and hub.properties.sunsetHour
  if not sunset then self:debug("no sunset info") return end
  local h, m = sunset:match("(%d+):(%d+)")
  if not h then return end
  local now = os.date("*t")
  local target = os.time{year = now.year, month = now.month, day = now.day,
                         hour = tonumber(h), min = tonumber(m)} + OFFSET * 60
  if target <= os.time() then target = target + 24 * 3600 end
  self._sunTimer = setTimeout(function()
    self._sunTimer = nil
    self:turnOn()
    self:scheduleNext()
  end, (target - os.time()) * 1000)
end

-- UI: the slider changes the offset the QA schedules with — the pending
-- timer is re-planned immediately, not at the next daily re-check
function QuickApp:_setOffset(event)
  local v = tonumber(event.values and event.values[1])
  if not v then return end
  OFFSET = v
  self:setVariable("offset", v)
  self:updateView("offsetSlider", "value", tostring(v))
  if LIGHT ~= 0 then
    if self._sunTimer then clearTimeout(self._sunTimer) end
    self:scheduleNext()
  end
end

function QuickApp:turnOn()
  fibaro.call(LIGHT, "turnOn")
  self:debug("light on")
end
