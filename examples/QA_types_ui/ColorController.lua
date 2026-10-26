
--%%name:ColorController
--%%type:com.fibaro.colorController
-- Color controller type should handle actions: turnOn, turnOff, setValue, setColor
-- To update color controller state, update property color with a string in the following format: "r,g,b,w" eg. "200,10,100,255"
-- To update brightness, update property "value" with integer 0-99
function QuickApp:turnOn()
    self:debug("color controller turned on")
    self:updateProperty("value", 99)
end

function QuickApp:turnOff()
    self:debug("color controller turned off")
    self:updateProperty("value", 0)    
end

-- Value is type of integer (0-99)
function QuickApp:setValue(value)
    self:debug("color controller value set to: ", value)
    self:updateProperty("value", value)    
end

-- Color is type of table, with format [r,g,b,w]
-- Eg. relaxing forest green, would look like this: [34,139,34,150]
function QuickApp:setColor(r,g,b,w)
    local color = string.format("%d,%d,%d,%d", r or 0, g or 0, b or 0, w or 0) 
    self:debug("color controller color set to: ", color)
    self:updateProperty("color", color)
    self:setColorComponents({red=r, green=g, blue=b, warmWhite=w})
end

function QuickApp:setColorComponents(colorComponents)
    local cc = self.properties.colorComponents
    local isColorChanged = false
    for k,v in pairs(colorComponents) do
        if cc[k] and cc[k] ~= v then
            cc[k] = v
            isColorChanged = true
        end
    end
    if isColorChanged == true then
        self:updateProperty("colorComponents", cc)
        self:setColor(cc["red"], cc["green"], cc["blue"], cc["warmWhite"])
    end
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
    self:updateProperty("colorComponents", {red=0, green=0, blue=0, warmWhite=0})
end
