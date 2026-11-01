--%%name:CoDetector
--%%type:com.fibaro.coDetector
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "setValue", bool) / "breach" / "clearBreach"

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
end
function QuickApp:setValue(state)
  self:updateProperty("value", state == true)
end

-- a breached sensor is its value: the HC3 sensor contract carries no
-- separate breached property (that is alarm partitions)
function QuickApp:breach()
  self:setValue(true)
end

function QuickApp:clearBreach()
  self:setValue(false)
end

