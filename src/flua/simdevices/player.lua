--%%name:Player
--%%type:com.fibaro.player
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "play" / "pause" / "stop" / "next" / "prev")
--   fibaro.call(id, "setVolume", 0-100) / "setMute", bool)

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
end
function QuickApp:play() self:updateProperty("state", "Play") end
function QuickApp:pause() self:updateProperty("state", "Pause") end
function QuickApp:stop() self:updateProperty("state", "Stop") end
function QuickApp:next() self:updateProperty("state", "Next") end
function QuickApp:prev() self:updateProperty("state", "Prev") end

-- 0-100
function QuickApp:setVolume(volume)
  volume = tonumber(volume)
  if volume then self:updateProperty("volume", volume) end
end

-- true/false (the HC3 UI sends 0/1)
function QuickApp:setMute(mute)
  self:updateProperty("mute", mute == 1 or mute == true)
end

