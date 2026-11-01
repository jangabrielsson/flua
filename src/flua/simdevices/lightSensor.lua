--%%name:LightSensor
--%%type:com.fibaro.lightSensor
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "setValue", 320, "lux")  -- value + optional unit

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
end
function QuickApp:setValue(value, unit)
  value = tonumber(value)
  if value then self:updateProperty("value", value) end
  if unit then self:updateProperty("unit", unit) end
end

function QuickApp:setUnit(unit)
  if unit then self:updateProperty("unit", unit) end
end

