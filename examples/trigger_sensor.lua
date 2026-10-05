--%%name:motion-sensor
-- Multi-QA debugging demo (docs/tutorial/10-multi-qa-debugging.md): the
-- sensor finds the lamp by name and toggles it every 600 ms, then exits.
-- Run with:
--   .venv/bin/flua --api local examples/trigger_sensor.lua examples/trigger_lamp.lua

local function findLamp()
  for _, d in ipairs(api.get("/devices?interface=quickApp")) do
    if d.name == "trigger-lamp" then return d.id end
  end
  return nil
end

function QuickApp:onInit()
  self:debug("sensor online")
  local n = 0
  setInterval(function()
    n = n + 1
    local lamp = findLamp()
    if lamp then
      fibaro.call(lamp, "toggle")
    else
      self:warning("no lamp found yet")
    end
    if n >= 3 then os.exit() end
  end, 600)
end
