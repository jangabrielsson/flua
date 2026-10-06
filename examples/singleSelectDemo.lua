--%%name:single_select_demo
--%%type:com.fibaro.genericDevice
--%%property:useUiView=true
--%%property:typeTemplateInitialized=true
--%%property:userDescription=
--%%u:{select='modeSelector',text='Modes',options={{type='option',text='Auto',value='auto'},{type='option',text='Manual',value='manual'},{type='option',text='Eco',value='eco'}},onToggled='modeSelection'}
--%%u:{{button='button_ID_1_1',text='change options',onReleased='changeOptions'},{button='button_ID_1_2',text='change options 2',onReleased='changeOptions2'}}
--%%u:{button='button_ID_2_1',text='set auto',onReleased='setAuto'}
--%%u:{button='button_ID_3_1',text='clear',onReleased='clearOptions'}
-- --------------- EOH ---------------
-- Generic device type have no default actions to handle

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

function QuickApp:modeSelection(event)
    print(json.encode(event))
    self.mode = event.values[1]

    print(self.mode)
    self:updateView("modeSelector", "selectedItem", self.mode)
end

function QuickApp:changeOptions()
    -- sample init of select options with translations 
    local flowOptions = {
        {
            text = "Auto",
            type = "option",
            value = "auto"
        },
        {
            text = "Manual",
            type = "option",
            value = "manual"
        },
        {
            text = "Eco",
            type = "option",
            value = "eco"
        },
        {
            text = "Turbo",
            type = "option",
            value = "turbo"
        }   
    }

    self:updateView("modeSelector", "options", flowOptions)
end

function QuickApp:changeOptions2()
    -- sample init of select options with translations 
    local flowOptions = {
        {
            text = "Auto",
            type = "option",
            value = "auto"
        },
        {
            text = "Manual",
            type = "option",
            value = "manual"
        }
    }

    self:updateView("modeSelector", "options", flowOptions)
end

function QuickApp:setAuto()
    self:updateView("modeSelector", "selectedItem", "auto")
end

function QuickApp:clearOptions()
    self:updateView("modeSelector", "selectedItem", "")
end