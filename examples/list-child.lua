--%%name:speaker list child demo
--%%type:com.fibaro.genericDevice
--%%useUiView:true

-- (NOT USABLE ON THE HC3: live-verified 5.22x — lists render only
--  from a plugin's packaged view file, a child's uiView blanks too.
--  Keep this demo for the flua viewer.)
-- The data-bound list hosted on a CHILD device — the live-probe companion
-- to examples/list.lua (which hosts the same list on the main QA). Child
-- UIs are the one HC3 place the editor never rewrites, and their bindings
-- fire as device actions on the child's class (the template's actionNames
-- are already the method names). The QA feeds plain rows at runtime:
--   child:updateView("speakersVolumeList", "data", { {playerId=..., ...}, ... })
-- Run with:
--   .venv/bin/flua --ui 8090 examples/list-child.lua
-- Upload with:
--   .venv/bin/flua --tool uploadQA examples/list-child.lua
--%%rsrc:speakersList:{list="speakersVolumeList",components={
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

Child = {}
class "Child"(QuickAppChild)
function Child:__init(dev) QuickAppChild.__init(self, dev) end
function Child:togglePlayerMute(id) print(self.name, "MUTE", id) end
function Child:setPlayerVolume(id, v) print(self.name, "VOL", id, v) end

function QuickApp:onInit()
  if _FLUA then _FLUA.keepAlive() end
  self:debug("speaker list child demo ready")
  local child = self:createChildDevice({
    name = "Speakers",
    type = "com.fibaro.doorSensor",
    initialProperties = { uiView = fibaro.RSRC.speakersList },
  }, Child)
  child:updateView("speakersVolumeList", "data", {
    {playerId = "player1", playerName = "Kitchen", playerVolume = 30,
     playerMuteStateImage = "SpeakerSimpleHigh"},
    {playerId = "player2", playerName = "Living room", playerVolume = 65,
     playerMuteStateImage = "SpeakerSimpleSlash"},
  })
end
