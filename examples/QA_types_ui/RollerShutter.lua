--%%name:RollerShutter
--%%type:com.fibaro.rollerShutter

-- Roller shutter type should handle actions: open, close, stop
-- To update roller shutter state, update property "value" with integer 0-99

function QuickApp:open()
    self:debug("roller shutter opened")
    self:updateProperty("value", 99)
end

function QuickApp:close()
    self:debug("roller shutter closed")
    self:updateProperty("value", 0)    
end

function QuickApp:stop()
    self:debug("roller shutter stopped ")
end

-- Value is type of integer (0-99)
function QuickApp:setValue(value)
    self:debug("roller shutter set to: " .. tostring(value))
    self:updateProperty("value", value)    
end

-- To update controls you can use method self:updateView(<component ID>, <component property>, <desired value>). Eg:  
-- self:updateView("slider", "value", "55") 
-- self:updateView("button1", "text", "MUTE") 
-- self:updateView("label", "text", "TURNED ON") 

-- This is QuickApp inital method. It is called right after your QuickApp starts (after each save or on gateway startup). 
-- Here you can set some default values, setup http connection or get QuickApp variables.
-- To learn more, please visit: 
--    * https://manuals.fibaro.com/home-center-3/
--    * https://manuals.fibaro.com/home-center-3-quick-apps/

function QuickApp:onInit()
    self:debug("onInit")
end
