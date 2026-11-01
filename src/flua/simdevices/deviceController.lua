--%%name:DeviceController
--%%type:com.fibaro.deviceController
--%%description:"Simulated device bundled with flua"

-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "createChild")  -- adds a child binary switch

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
end
QuickAppChild = QuickAppChild or {}
MyBinarySwitch = {}
class 'MyBinarySwitch'(QuickAppChild)
function MyBinarySwitch:__init(device)
  QuickAppChild.__init(self, device)
end
function MyBinarySwitch:turnOn() self:updateProperty("value", true) end
function MyBinarySwitch:turnOff() self:updateProperty("value", false) end

-- createChild() adds a child binary switch; drive it with
-- fibaro.call(childId, "turnOn"/"turnOff")
function QuickApp:createChild()
  local child = self:createChildDevice({
    name = "child",
    type = "com.fibaro.binarySwitch",
  }, MyBinarySwitch)
  self:debug("child created, id", child.id)
  return child.id
end

