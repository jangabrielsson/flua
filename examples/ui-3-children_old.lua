--%%name:ui 3 children
--%%type:com.fibaro.genericDevice
--%%useUiView:true

-- Three children sharing one Child class, each with its own child-bound
-- uiView: A a tabbed panel, B a collapsible, C six buttons in a row plus
-- an image. Child UI events arrive as device actions: the binding's
-- actionName IS the method on the child's class (children never register
-- a uiCallbacks table), with plain args — live-verified 5.221. The
-- uiViews were generated with:  flua --tool ui --as-lua --child <file>

Child = {}
class "Child"(QuickAppChild)
function Child:__init(dev) QuickAppChild.__init(self, dev) end

-- the shared methods (plain args, no event table)
function Child:tabChanged(tab) print(self.name, "TAB", tab) end
function Child:turnOn() print(self.name, "Turn On") end
function Child:dim(v) print(self.name, "Brightness", v) end
function Child:handleSwitch(v) print(self.name, "Auto", v) end
function Child:handleSelect(v) print(self.name, "Mode", v) end
function Child:play() print(self.name, "Play") end
function Child:press() print(self.name, "Button pressed") end

local uiViewA = {{style={weight='1.0'},type='horizontal',components={{type='tabView',name='mainTabs',activeTab='control',visible=true,style={weight='1'},eventBinding={onTabChanged={{type='deviceAction',params={actionName='tabChanged',args={'$event.value'}}}}},tabs={{type='tab',name='control',text='Control',style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{name='ctlLbl',style={weight='1.0'},text='No action yet',type='label',visible=true}}},{style={weight='1.0'},type='horizontal',components={{eventBinding={onReleased={{type='deviceAction',params={actionName='turnOn',args=json.array()}}}},name='onBtn',style={weight='1.0'},text='Turn On',type='button',visible=true}}},{style={weight='1.0'},type='horizontal',components={{eventBinding={onChanged={{type='deviceAction',params={actionName='dim',args={'$event.value'}}}}},name='dim',style={weight='1.0'},text='Brightness',type='slider',visible=true,max='100',min='0',step='1',value='50'}}}}},{type='tab',name='settings',text='Settings',style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{eventBinding={onReleased={{type='deviceAction',params={actionName='handleSwitch',args=json.array()}}}},name='auto',style={weight='1.0'},text='Auto mode',type='switch',visible=true,value='false'}}},{style={weight='1.0'},type='horizontal',components={{eventBinding={onToggled={{type='deviceAction',params={actionName='handleSelect',args={'$event.value'}}}}},name='mode',style={weight='1.0'},text='Mode',type='select',visible=true,options={{type='option',text='Economy',value='1'},{type='option',text='Comfort',value='2'}},values={'1'},selectionType='single'}}}}},{type='tab',name='about',text='About',style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{name='aboutLbl',style={weight='1.0'},text='tabView demo — click the tabs (the QA logs each click)',type='label',visible=true}}}}}}}}}}
local uiViewB = {{style={weight='1.0'},type='horizontal',components={{type='collapsible',name='favs',text='Favorites',collapsed=false,disabled=false,visible=true,style={weight='1'},components={{style={weight='1.0'},type='horizontal',components={{name='lbl',style={weight='1.0'},text='Tap the header to collapse',type='label',visible=true}}},{style={weight='1.0'},type='horizontal',components={{eventBinding={onReleased={{type='deviceAction',params={actionName='play',args=json.array()}}}},name='play',style={weight='1.0'},text='Play',type='button',visible=true}}}}}}}}
local uiViewC = {{style={weight='1.0'},type='horizontal',components={{eventBinding={onReleased={{type='deviceAction',params={actionName='press',args=json.array()}}}},name='b1',style={weight='0.16'},text='1',type='button',visible=true},{eventBinding={onReleased={{type='deviceAction',params={actionName='press',args=json.array()}}}},name='b2',style={weight='0.16'},text='2',type='button',visible=true},{eventBinding={onReleased={{type='deviceAction',params={actionName='press',args=json.array()}}}},name='b3',style={weight='0.16'},text='3',type='button',visible=true},{eventBinding={onReleased={{type='deviceAction',params={actionName='press',args=json.array()}}}},name='b4',style={weight='0.16'},text='4',type='button',visible=true},{eventBinding={onReleased={{type='deviceAction',params={actionName='press',args=json.array()}}}},name='b5',style={weight='0.16'},text='5',type='button',visible=true},{eventBinding={onReleased={{type='deviceAction',params={actionName='press',args=json.array()}}}},name='b6',style={weight='0.16'},text='6',type='button',visible=true}}},{style={weight='1.0'},type='horizontal',components={{name='art',style={weight='1.0'},text='',type='image',visible=true,url='https://placehold.co/120x48?text=flua',image='art'}}}}

function QuickApp:onInit()
  if _FLUA then _FLUA.keepAlive() end
  self:initChildDevices({
    ["com.fibaro.floodSensor"] = Child,
    ["com.fibaro.doorSensor"] = Child,
    ["com.fibaro.windowSensor"] = Child,
  })
  local tmap = {}
  for _, c in ipairs(self.childDevices) do tmap[c.type] = true end
  if not tmap["com.fibaro.floodSensor"] then
    self:createChildDevice(
      { name = "A", type = "com.fibaro.floodSensor",
        initialProperties = { uiView = uiViewA } }, Child)
  end
  if not tmap["com.fibaro.doorSensor"] then
    self:createChildDevice(
      { name = "B", type = "com.fibaro.doorSensor",
        initialProperties = { uiView = uiViewB } }, Child)
  end
  if not tmap["com.fibaro.windowSensor"] then
    self:createChildDevice(
      { name = "C", type = "com.fibaro.windowSensor",
        initialProperties = { uiView = uiViewC } }, Child)
  end
end
