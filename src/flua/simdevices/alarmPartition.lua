--%%name:AlarmPartition
--%%type:com.fibaro.alarmPartition
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "arm" / "disarm" / "setArmed", bool) / "breached", bool)

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
end
function QuickApp:arm() self:setArmed(true) end
function QuickApp:disarm() self:setArmed(false) end

function QuickApp:setArmed(armed)
  self:updateProperty("armed", armed == true)
end

-- the alarm partition was breached: alarm = true
function QuickApp:breached(state)
  self:updateProperty("alarm", state == true)
end

