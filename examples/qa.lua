--%%name:Test
--%%type:com.fibaro.binarySwitch
--%%uid:836r26r827r67823
--%%description:my little QA
--%%model:model-x
--%%build:7
--%%manufacturer:fibaro
--%%property:value=true
--%%var:bar="Hello"

function QuickApp:onInit()
    self:debug("QuickApp initialized")
    self:debug("Name", self.name)
    self:debug("Type", self.type)
    self:debug("ID", self.id)

    self:debug("UID",self.properties.quickAppUuid)
    self:debug("Description", self.properties.userDescription)
    self:debug("Model", self.properties.model)
    self:debug("Build", self.properties.buildNumber)
    self:debug("Manufacturer", self.properties.manufacturer)
    self:debug("Value property", self.properties.value)

    self:trace("TRACE")
    self:warning("WARNING")
    self:error("ERROR")

    self:debug("Bar variable", self:getVariable("bar"))

    self:setVariable("foo", {1,2,3})
    local foo = self:getVariable("foo")
    self:debug("QA variable foo", json.encode(foo))

    self:internalStorageSet("foo", {1,2,3})
    local iv = self:internalStorageGet("foo")
    self:debug("Internal storage variable", json.encode(iv))

    local iv = setInterval(function() print("OK") end, 1000)
    setTimeout(function() print("Timeout reached") clearInterval(iv)  end, 5000)
end