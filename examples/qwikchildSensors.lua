--%%name:QwikChildSensors
--%%type:com.fibaro.deviceController

--%%file:$qwikchild.lua,qwikchild

local fmt = string.format

local children = {
  ['S1'] = {
    name = 'ChildA',
    type = 'com.fibaro.multilevelSensor',
    className = 'SensorChild',
    UI = {
      {label='l1', text="..."},
    }
  },
  ['S2'] = {
    name = 'ChildB',
    type = 'com.fibaro.multilevelSensor',
    className = 'SensorChild',
    UI = {
      {label='l1', text="..."},
    }
  }
}

function QuickApp:onInit()
  self:debug(self.name, self.id)
  self:initChildren(children)
  self.children.S1:setValue(50.5)
  self.children.S2:setValue(75.3)
end

SensorChild = {}

class 'SensorChild'(QwikAppChild)
function SensorChild:__init(dev)
  QwikAppChild.__init(self, dev)
  self:updateProperty("unit","kWh")
  self:updateProperty("log","Hello world")
end
function SensorChild:setValue(value) 
  self:updateProperty('value', value)
  --self:updateView('value', 'text', fmt("value: %s", value))
end

