--%%name:binary
--%%type:com.fibaro.binarySwitch

-- Binary switch with on/off embedded UI elements

function QuickApp:onInit()
    self:debug("onInit")
end

function QuickApp:turnOn()
  self:debug("turnOn")
  self:updateProperty('value', true)
end

function QuickApp:turnOff()
  self:debug("turnOff")
  self:updateProperty('value', false)
end