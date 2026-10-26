--%%name:Player
--%%type:com.fibaro.player
-- Player type should handle actions: play, pause, stop, next, prev, setVolume, setMute
-- To update player state, update properties:
-- * "volume" with integer 0-100
-- * "mute" with boolean
-- * "power" with boolean

function QuickApp:play()
    self:debug("handle play")
end

function QuickApp:pause()
    self:debug("handle pause")
end

function QuickApp:stop()
    self:debug("handle stop")
end

function QuickApp:next()
    self:debug("handle next")
end

function QuickApp:prev()
    self:debug("handle prev")
end

function QuickApp:setVolume(volume)
    self:debug("setting volume to:", volume)
    self:updateProperty("volume", volume)
end

function QuickApp:setMute(mute)
    if mute == 0 then 
        self:debug("setting mute to:", false)
        self:updateProperty("mute", false)
    else
        self:debug("setting mute to:", true)
        self:updateProperty("mute", true)
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
end
