--%%name:child ui demo
--%%type:com.fibaro.genericDevice
--%%useUiView:true

-- A child device whose uiView carries v2 elements (tabView + collapsible).
-- Child UIs are the one HC3 place the editor never rewrites, so they are
-- safe there — and child UI events arrive as DEVICE ACTIONS: the binding's
-- actionName IS the method on the child's class (children have no
-- uiCallbacks table; live-verified 5.221). The uiView below was generated
-- with:  flua --tool ui --as-lua --child <file-with---%%u-rows>
-- Run locally with:
--   .venv/bin/flua --ui 8090 examples/child-ui.lua
-- Upload with:
--   .venv/bin/flua --tool uploadQA examples/child-ui.lua
local uiView = {{style={weight='1.0'},type='horizontal',components={{type='tabView',name='mainTabs',activeTab='control',visible=true,style={weight='1'},eventBinding={onTabChanged={{type='deviceAction',params={actionName='tabChanged',args={'$event.value'}}}}},tabs={{type='tab',name='control',text='Control',style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{eventBinding={onReleased={{type='deviceAction',params={actionName='turnOn',args={}}}}},name='onBtn',style={weight='1.0'},text='Turn On',type='button',visible=true}}},{style={weight='1.0'},type='horizontal',components={{eventBinding={onChanged={{type='deviceAction',params={actionName='dim',args={'$event.value'}}}}},name='dim',style={weight='1.0'},text='Brightness',type='slider',visible=true,max='100',min='0',step='1',value='50'}}}}},{type='tab',name='settings',text='Settings',style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{eventBinding={onReleased={{type='deviceAction',params={actionName='handleSwitch',args={}}}}},name='auto',style={weight='1.0'},text='Auto mode',type='switch',visible=true,value='false'}}},{style={weight='1.0'},type='horizontal',components={{eventBinding={onToggled={{type='deviceAction',params={actionName='handleSelect',args={'$event.value'}}}}},name='mode',style={weight='1.0'},text='Mode',type='select',visible=true,options={{type='option',text='Economy',value='1'},{type='option',text='Comfort',value='2'}},values={'1'},selectionType='single'}}}}}}}}},{style={weight='1.0'},type='horizontal',components={{type='collapsible',name='favs',text='Favorites',collapsed=false,disabled=false,visible=true,style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{eventBinding={onReleased={{type='deviceAction',params={actionName='play',args={}}}}},name='play',style={weight='1.0'},text='Play',type='button',visible=true}}}}}}}}

Child = {}
class 'Child'(QuickAppChild)
function Child:__init(dev) QuickAppChild.__init(self, dev) end

-- the child UI's methods: called by the HC3 (and flua) via
-- child:callAction(actionName, args...) — plain args, no event table
function Child:tabChanged(tab) print(self.name, "TAB CHANGED TO", tab) end
function Child:turnOn() print(self.name, "Turn On pressed") end
function Child:dim(v) print(self.name, "Brightness", v) end
function Child:handleSwitch(v) print(self.name, "Auto mode", v) end
function Child:handleSelect(v) print(self.name, "Mode", v) end
function Child:play() print(self.name, "Play pressed") end

function QuickApp:onInit()
  _FLUA.keepAlive()
  self:debug("child ui demo ready")
  for _, c in ipairs(self.childDevices) do
    if c.type == "com.fibaro.floodSensor" then return end  -- already created
  end
  self:createChildDevice(
    {
      name = "Tabs child",
      type = "com.fibaro.floodSensor",
      initialProperties = { uiView = uiView },
    },
    Child
  )
end
