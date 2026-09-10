--%%name:Test
--%%type:com.fibaro.binarySwitch

function QuickApp:onInit()
    self:debug("QuickApp initialized")
    self:debug("Name", self.name)
    self:debug("Type", self.type)
    self:debug("ID", self.id)

    self:trace("TRACE")
    self:warning("WARNING")
    self:error("ERROR")

    local iv = setInterval(function() print("OK") end, 1000)
    setTimeout(function() print("Timeout reached") clearInterval(iv)  end, 5000)
end