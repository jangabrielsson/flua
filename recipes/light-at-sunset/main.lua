--%%name:Light at sunset
--%%type:com.fibaro.deviceController
-- =====================================================================
-- RECIPE — edit these lines, then upload (flua --tool uploadQA main.lua)
--%%var:deviceId=0        -- the light's device id (com.fibaro.binarySwitch)
--%%var:offset=-30        -- minutes before (-) / after (+) sunset
-- =====================================================================
-- --------------- EOH ---------------
local LIGHT = tonumber(self:getVariable("deviceId")) or 0
local OFFSET = tonumber(self:getVariable("offset")) or -30

function QuickApp:onInit()
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
  setTimeout(function()
    self:turnOn()
    self:scheduleNext()
  end, (target - os.time()) * 1000)
end

function QuickApp:turnOn()
  api.post("/devices/" .. LIGHT .. "/action/turnOn")
  self:debug("light on")
end
