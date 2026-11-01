--%%name:HvacSystemHeat
--%%type:com.fibaro.hvacSystemHeat
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "setThermostatMode", "Heat")
--   fibaro.call(id, "setHeatingThermostatSetpoint", 21)

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
  self:updateProperty("supportedThermostatModes", {"Off", "Heat"})
end
function QuickApp:setThermostatMode(mode)
  self:updateProperty("thermostatMode", mode)
end

function QuickApp:setHeatingThermostatSetpoint(value, unit)
  value = tonumber(value)
  if value then
    self:updateProperty("heatingThermostatSetpoint", { value = value, unit = unit or "C" })
  end
end

