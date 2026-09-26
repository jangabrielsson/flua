--%%name:ChildrenLocal
--%%type:com.fibaro.binarySwitch

--%%debug:api=true
--%%mode:offline

function QuickApp:onInit()
  print("ChildrenLocal initialized")
  self:checkChildren()
  self:createChildren()
  self:checkChildren()
  local d = api.get("/devices")
  for _, device in ipairs(d) do
    print("Found device: "..(device.name or "unknown"))
  end
  self:deleteChildren()
  self:checkChildren()
end

function QuickApp:checkChildren()
  print("Checking children:")
  local children = api.get("/devices?parentId="..self.id)
  for _, child in ipairs(children) do
    print("Found child: "..(child.name or "unknown"))
  end
end

Child1 = {}
class 'Child1'(QuickAppChild)
function Child1:__init(dev)
  QuickAppChild.__init(self,dev)
end

Child2 = {}
class 'Child2'(QuickAppChild)
function Child2:__init(dev)
  QuickAppChild.__init(self,dev)
end

Child3 = {}
class 'Child3'(QuickAppChild)
function Child3:__init(dev)
  QuickAppChild.__init(self,dev)
end

function QuickApp:createChildren()
  print("Creating children:")
  local c1 = self:createChildDevice(
  {
    name='Child1',
    type='com.fibaro.binarySwitch'
  }, Child1)
  local c2 = self:createChildDevice(
  {
    name='Child2',
    type='com.fibaro.binarySwitch'
  }, Child2)
  local c3 = self:createChildDevice(
  {
    name='Child3',
    type='com.fibaro.binarySwitch'
  }, Child3)
end

function QuickApp:deleteChildren()
  print("Deleting children:")
  local children = api.get("/devices?parentId="..self.id)
  for _, child in ipairs(children) do
    api.delete("/plugins/removeChildDevice/" .. child.id)
  end
end