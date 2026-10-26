--%%name:BaseShutter
--%%type:com.fibaro.baseShutter

-- Base shutter type should handle actions: open, close, stop
-- Base shutter supports "state" property with possible values: Opening, Opened, Closing, Closed

function QuickApp:open()
    self:debug("base shutter opened")
    self:updateProperty("state", "Opened")
end

function QuickApp:close()
    self:debug("base shutter closed")
    self:updateProperty("state", "Closed")
end

function QuickApp:stop()
    self:debug("base shutter stopped")
    self:updateProperty("state", "Unknown")
end

function QuickApp:onInit()
    self:debug("onInit")
end
