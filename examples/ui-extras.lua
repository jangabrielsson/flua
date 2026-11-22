--%%name:ui extras demo
--%%type:com.fibaro.genericDevice
--%%useUiView:true
-- (useUiView is required on the real HC3 for the full-width v2 elements
-- — the collapsible here, like the tabView demo: the app draws them from
-- the uiView format; the legacy $jason renderer leaves them blank. They
-- are NOT editable in the HC3's UI editor — keep this QA flua-authored,
-- update via updateQA)

-- An image shows a picture from its url (live-updatable via updateView);
-- a collapsible is a full-width section header that expands/collapses its
-- rows (client-side state, no event). Run with:
--   .venv/bin/flua --ui 8090 examples/ui-extras.lua
-- (the QA drains after ~1s of demo timers; add --%%keep-alive:true to keep
-- it alive while you play with the viewer)
--%%u:{image="art",url="https://placehold.co/120x80?text=flua"}
--%%u:{collapsible="favs",text="Favorites",collapsed=false,components={
--  {{label="lbl",text="Inside the collapsible"}},
--  {{button="play",text="Play",onReleased="play"}}
--}}

function QuickApp:onInit()
  self:debug("ui extras demo ready")
  -- updateView reaches elements inside the collapsible AND swaps the
  -- image's url (the viewer follows both)
  setTimeout(function()
    self:updateView("lbl", "text", "updated from updateView")
    self:updateView("art", "url", "https://placehold.co/120x80?text=flua!")
  end, 500)
end

function QuickApp:play()
  print("Play pressed")
end
