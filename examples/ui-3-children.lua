--%%name:ui 3 children
--%%type:com.fibaro.genericDevice
--%%useUiView:true

-- Three children: A gets a tabbed child uiView (v2 elements are safe on
-- children — the editor never rewrites them). Child UI events arrive as
-- DEVICE ACTIONS: the binding's actionName IS the method on the child's
-- class (no uiCallbacks table, live-verified 5.221). uiView generated with:
--   flua --tool ui --as-lua --child examples/tabs.lua

Child = {}
class "Child"(QuickAppChild)
function Child:__init(dev) QuickAppChild.__init(self, dev) end

-- child methods: called via child:callAction(actionName, args...)
-- plain arguments, no event table
function Child:tabChanged(tab) print(self.name, "TAB CHANGED TO", tab) end
function Child:turnOn()
  print(self.name, "Turn On pressed")
  self:updateView("ctlLbl", "text", "Turned on!")
end
function Child:dim(v) print(self.name, "Brightness", v) end
function Child:handleSwitch(v) print(self.name, "Auto mode", v) end
function Child:handleSelect(v) print(self.name, "Mode", v) end
function Child:play() print(self.name, "Play pressed") end

local uiView1 = {{style={weight='1.0'},type='horizontal',components={{type='tabView',name='mainTabs',activeTab='control',visible=true,style={weight='1'},eventBinding={onTabChanged={{type='deviceAction',params={actionName='tabChanged',args={'$event.value'}}}}},tabs={{type='tab',name='control',text='Control',style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{name='ctlLbl',style={weight='1.0'},text='No action yet',type='label',visible=true}}},{style={weight='1.0'},type='horizontal',components={{eventBinding={onReleased={{type='deviceAction',params={actionName='turnOn',args={}}}}},name='onBtn',style={weight='1.0'},text='Turn On',type='button',visible=true}}},{style={weight='1.0'},type='horizontal',components={{eventBinding={onChanged={{type='deviceAction',params={actionName='dim',args={'$event.value'}}}}},name='dim',style={weight='1.0'},text='Brightness',type='slider',visible=true,max='100',min='0',step='1',value='50'}}}}},{type='tab',name='settings',text='Settings',style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{eventBinding={onReleased={{type='deviceAction',params={actionName='handleSwitch',args={}}}}},name='auto',style={weight='1.0'},text='Auto mode',type='switch',visible=true,value='false'}}},{style={weight='1.0'},type='horizontal',components={{eventBinding={onToggled={{type='deviceAction',params={actionName='handleSelect',args={'$event.value'}}}}},name='mode',style={weight='1.0'},text='Mode',type='select',visible=true,options={{type='option',text='Economy',value='1'},{type='option',text='Comfort',value='2'}},values={'1'},selectionType='single'}}}}},{type='tab',name='about',text='About',style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{name='aboutLbl',style={weight='1.0'},text='tabView demo — click the tabs (the QA logs each click)',type='label',visible=true}}}}}}}}}}

function QuickApp:onInit()
  _FLUA.keepAlive()
  self:initChildDevices({
    ["com.fibaro.floodSensor"] = Child,
    ["com.fibaro.doorSensor"] = Child,
    ["com.fibaro.windowSensor"] = Child,
  })
  local tmap = {}
  for _, c in ipairs(self.childDevices) do tmap[c.type] = true end
  if not tmap["com.fibaro.floodSensor"] then
    self:createChildDevice(
      {
        name = "A",
        type = "com.fibaro.floodSensor",
        initialProperties = { uiView = uiView1 },
      },
      Child
    )
  end
  if not tmap["com.fibaro.doorSensor"] then
    self:createChildDevice({ name = "B", type = "com.fibaro.doorSensor" }, Child)
  end
  if not tmap["com.fibaro.windowSensor"] then
    self:createChildDevice({ name = "C", type = "com.fibaro.windowSensor" }, Child)
  end
end
