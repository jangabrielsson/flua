--%%name:speaker list demo
--%%type:com.fibaro.genericDevice
--%%useUiView:true
-- (the list element is v2-only — the --check guard warns without this)
-- (NOT USABLE ON THE HC3: live-verified 5.22x that the app renders
--  lists only from a plugin's packaged view file — every template
--  shape blanks from a QA's uiView. Keep this demo for the flua
--  viewer; the implementation stays for future app support.)

-- The HC3's data-bound list (the sonosGroup speaker rows). The element's
-- components is the ITEM TEMPLATE in the raw uiView dialect:
-- {{data.<field>}} placeholders wherever an item's value goes (text,
-- image, slider value) and in the event args — the binding fires per item
-- with the item's fields resolved. The QA feeds plain rows at runtime:
--   self:updateView("speakersVolumeList", "data", { {playerId=..., ...}, ... })
-- Run with:
--   .venv/bin/flua --ui 8090 examples/list.lua
-- (add --%%keep-alive:true, or the guard below keeps it alive, to play
-- with the viewer)
--%%u:{list="speakersVolumeList",components={
--  {type="horizontal",components={
--    {type="label",name="speakerName_Label",text="{{data.playerName}}"},
--    {type="button",name="toggleMute_Button",text="Mute",image="{{data.playerMuteStateImage}}",
--      eventBinding={onReleased={{type="deviceAction",params={actionName="togglePlayerMute",args={"{{data.playerId}}"}}}}}}
--  }},
--  {type="horizontal",components={
--    {type="slider",name="volume_Slider",min="0",max="100",step="1",value="{{data.playerVolume}}",
--      eventBinding={onChanged={{type="deviceAction",params={actionName="setPlayerVolume",args={"{{data.playerId}}","$event.value"}}}}}}
--  }}
--}}

function QuickApp:onInit()
  if _FLUA then _FLUA.keepAlive() end
  self:debug("speaker list demo ready")
  -- the rows: plain fields, no view structure
  self:updateView("speakersVolumeList", "data", {
    {playerId = "player1", playerName = "Kitchen", playerVolume = 30,
     playerMuteStateImage = "SpeakerSimpleHigh"},
    {playerId = "player2", playerName = "Living room", playerVolume = 65,
     playerMuteStateImage = "SpeakerSimpleSlash"},
  })
end

function QuickApp:togglePlayerMute(id) print("MUTE", id) end
function QuickApp:setPlayerVolume(id, v) print("VOL", id, v) end
