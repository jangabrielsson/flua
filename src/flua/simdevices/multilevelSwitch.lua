--%%name:MultilevelSwitch
--%%type:com.fibaro.multilevelSwitch
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "turnOn" / "turnOff" / "setValue", 0-99)

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
end
function QuickApp:turnOn() self:setValue(99) end
function QuickApp:turnOff() self:setValue(0) end

-- 0-99 (off .. full brightness)
function QuickApp:setValue(value)
  value = tonumber(value)
  if value then self:updateProperty("value", value) end
end

