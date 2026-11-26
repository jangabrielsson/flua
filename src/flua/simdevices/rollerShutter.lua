--%%name:RollerShutter
--%%type:com.fibaro.rollerShutter
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
-- Mirrors the HC3's quickapp template (com.fibaro.rollerShutter): open/close
-- move the position (value 99/0), stop halts without changing it, setValue
-- positions the shutter anywhere 0-99.
--
--   fibaro.call(id, "open" / "close" / "stop")
--   fibaro.call(id, "setValue", 0-99)

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
  -- a numeric position from the first read (the skeleton may not carry one)
  self:updateProperty("value", tonumber(self.properties.value) or 0)
end

function QuickApp:open() self:setValue(99) end
function QuickApp:close() self:setValue(0) end

function QuickApp:stop()
  self:debug("roller shutter stopped")
end

-- value is 0-99 (closed .. open)
function QuickApp:setValue(value)
  value = tonumber(value)
  if value then self:updateProperty("value", value) end
end
