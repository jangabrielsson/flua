--%%name:ui 3 children
--%%type:com.fibaro.genericDevice
--%%useUiView:true

-- Three children sharing one Child class, each with its own child-bound
-- uiView declared as a RESOURCE: --%%rsrc:name:{...} compiles the row to
-- a child uiView (actionName = the method, json.array() for argless) and
-- makes it available as fibaro.RSRC.name — in flua directly, and on the
-- HC3 via a synthesized rsrc.lua the package ships. One directive is ONE
-- row (a bare dict = a single element, a list = several side by side);
-- repeated directives accumulate the resource's rows. Child UI events
-- arrive as device actions with plain args (children never register
-- uiCallbacks), live-verified 5.221.

--%%rsrc:uiA:{tabView="mainTabs",activeTab="control",onTabChanged="tabChanged",tabs={
--  {name="control",text="Control",components={
--    {{button="onBtn",text="Turn On",onReleased="turnOn"}},
--    {{slider="dim",text="Brightness",min="0",max="100",value="50",onChanged="dim"}}
--  }},
--  {name="settings",text="Settings",components={
--    {{switch="auto",text="Auto mode",value="false",onReleased="handleSwitch"}},
--    {{select="mode",text="Mode",value="1",onToggled="handleSelect",
--      options={{type='option',text='Economy',value='1'},{type='option',text='Comfort',value='2'}}}}
--  }},
--  {name="about",text="About",components={
--    {{label="aboutLbl",text="tabView demo — click the tabs (the QA logs each click)"}}
--  }}}}

--%%rsrc:uiB:{collapsible="favs",text="Favorites",collapsed=false,components={
--  {{label="lbl",text="Tap the header to collapse"}},
--  {{button="play",text="Play",onReleased="play"}}
--}}

--%%rsrc:uiC:{{button="b1",text="1",onReleased="press"},{button="b2",text="2",onReleased="press"},
--  {button="b3",text="3",onReleased="press"},{button="b4",text="4",onReleased="press"},
--  {button="b5",text="5",onReleased="press"},{button="b6",text="6",onReleased="press"}}
--%%rsrc:uiC:{image="art",url="https://placehold.co/120x48?text=flua"}

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
        initialProperties = { uiView = fibaro.RSRC.uiA } }, Child)
  end
  if not tmap["com.fibaro.doorSensor"] then
    self:createChildDevice(
      { name = "B", type = "com.fibaro.doorSensor",
        initialProperties = { uiView = fibaro.RSRC.uiB } }, Child)
  end
  if not tmap["com.fibaro.windowSensor"] then
    self:createChildDevice(
      { name = "C", type = "com.fibaro.windowSensor",
        initialProperties = { uiView = fibaro.RSRC.uiC } }, Child)
  end
end
