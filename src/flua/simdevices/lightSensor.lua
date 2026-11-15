--%%name:LightSensor
--%%type:com.fibaro.lightSensor
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "setValue", 320, "lux")  -- value + optional unit

--%%u:{slider='valueSlider',text='Value',min=0,max=30000,unit='lux',onChanged='_setValue'}

-- UI: the viewer delivers the slider's new value in event.values[1]
function QuickApp:_setValue(event)
  self:setValue(event.values and event.values[1])
end

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
  local value = tonumber(self.properties.value) or 0
  self:updateProperty("value", value)
  self:updateView("valueSlider", "value", tostring(value))
end
function QuickApp:setValue(value, unit)
  value = tonumber(value)
  if value then self:updateProperty("value", value) end
  if unit then self:updateProperty("unit", unit) end
end

function QuickApp:setUnit(unit)
  if unit then self:updateProperty("unit", unit) end
end

