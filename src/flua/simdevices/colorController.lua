--%%name:ColorController
--%%type:com.fibaro.colorController
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "turnOn" / "turnOff" / "setValue", 0-99)
--   fibaro.call(id, "setColor", r, g, b, w)  -- e.g. 34,139,34,150

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
  self:updateProperty("colorComponents", {red = 0, green = 0, blue = 0, warmWhite = 0})
end
function QuickApp:turnOn() self:setValue(99) end
function QuickApp:turnOff() self:setValue(0) end

-- brightness 0-99
function QuickApp:setValue(value)
  value = tonumber(value)
  if value then self:updateProperty("value", value) end
end

-- color "r,g,b,w" — e.g. relaxing forest green: 34,139,34,150
function QuickApp:setColor(r, g, b, w)
  local color = string.format("%d,%d,%d,%d", tonumber(r) or 0, tonumber(g) or 0,
    tonumber(b) or 0, tonumber(w) or 0)
  self:updateProperty("color", color)
  self:setColorComponents({red = r, green = g, blue = b, white = w})
end

function QuickApp:setColorComponents(colorComponents)
  local cc = self.properties.colorComponents or {}
  for k, v in pairs(colorComponents) do cc[k] = tonumber(v) or 0 end
  self:updateProperty("colorComponents", cc)
  self:setColor(cc["red"], cc["green"], cc["blue"], cc["white"])
end

