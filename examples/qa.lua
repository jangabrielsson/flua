--%%name:My QA
--%%type:com.fibaro.binarySwitch

function QuickApp:onInit()
    self:debug("QuickApp initialized")
    self:debug("Name", self.name)
    self:debug("Type", self.type)
    self:debug("ID", self.id)

    self:trace("TRACE")
    self:warning("WARNING")
    self:error("ERROR")
end