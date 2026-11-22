--%%name:tabView demo
--%%type:com.fibaro.genericDevice
--%%useUiView:true
-- (useUiView is required for tabView on the real HC3: the app draws tabs
-- from the uiView format — live-verified on 5.221; the legacy $jason
-- renderer leaves a tabView-only view blank)

-- A tabView groups rows under named tabs: full-width (alone on its row),
-- tabs take name/text and their own rows, the tabView takes activeTab and
-- an optional onTabChanged method. Run with:
--   .venv/bin/flua --ui 8090 examples/tabs.lua
-- (the QA drains after ~1s of demo timers; add --%%keep-alive:true to keep
-- it alive while you play with the viewer)
--%%u:{tabView="mainTabs",activeTab="control",onTabChanged="tabChanged",tabs={
--  {name="control",text="Control",components={
--    {{label="ctlLbl",text="No action yet"}},
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
--%%keep-alive:true 

function QuickApp:onInit()
  self:debug("tabView demo ready")
  -- updateView reaches elements INSIDE tabs, and switches tabs
  -- programmatically (the viewer follows)
  setTimeout(function()
    self:updateView("ctlLbl", "text", "updated from updateView")
    self:updateView("mainTabs", "activeTab", "settings")
  end, 500)
  setTimeout(function()
    self:updateView("mainTabs", "activeTab", "about")
  end, 1000)
end

function QuickApp:tabChanged(e)
  print("TAB CHANGED TO", e.values and e.values[1])
end

function QuickApp:turnOn()
  print("Turn On pressed")
  self:updateView("ctlLbl", "text", "Turned on!")
end

function QuickApp:dim(e)
  print("Brightness", e.values and e.values[1])
end

function QuickApp:handleSwitch(e)
  print("Auto mode", e.values and e.values[1])
end

function QuickApp:handleSelect(e)
  print("Mode", e.values and e.values[1])
end
