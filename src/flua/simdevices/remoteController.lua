--%%name:RemoteController
--%%type:com.fibaro.remoteController
--%%description:"Simulated device bundled with flua"
--%%interface:zwaveCentralScene
-- A simulated device: change its state from another QA (or the
-- debugger) and watch scenes/reacting QAs fire, exactly like a real
-- device would behave.
--
--   fibaro.call(id, "emitCentralSceneEvent", keyId, keyAttribute)

function QuickApp:onInit()
  self:debug("sim device ready, id", self.id)
  -- stay up for the whole run (a drained QA stops answering)
  _FLUA.keepAlive()
  -- scenes list possible triggers from this table
  self:updateProperty("centralSceneSupport", {
    { keyAttributes = { "Pressed", "Released", "HeldDown", "Pressed2", "Pressed3" }, keyId = 1 },
    { keyAttributes = { "Pressed", "Released", "HeldDown", "Pressed2", "Pressed3" }, keyId = 2 },
  })
end
function QuickApp:emitCentralSceneEvent(keyId, keyAttribute)
  if keyAttribute == nil then keyAttribute = "Pressed" end
  api.post("/plugins/publishEvent", {
    type = "centralSceneEvent",
    source = self.id,
    data = { keyAttribute = keyAttribute, keyId = keyId },
  })
end

