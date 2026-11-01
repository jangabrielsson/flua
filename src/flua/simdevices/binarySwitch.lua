--%%name:BinarySwitch
--%%type:com.fibaro.binarySwitch
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "turnOn" / "turnOff" / "setValue", bool)

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
end
function QuickApp:turnOn() self:setValue(true) end
function QuickApp:turnOff() self:setValue(false) end

function QuickApp:setValue(value)
  self:updateProperty("value", value == true)
end

