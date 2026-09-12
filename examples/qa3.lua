--%%name:qa-three
-- Example QA pair: QAs calling each other over the HC3 REST API.
-- Run with:
--   .venv/bin/flua examples/qa3.lua examples/qa4.lua
-- qa4 turns this QA on and off; this QA answers by calling qa4's "notify"
-- action. Device ids are assigned by the engine, so QAs find each other by
-- name through the API — the same pattern real HC3 QAs use.
local function findDevice(name)
  local devices = api.get('/devices?interface=quickApp')
  for _, dev in ipairs(devices) do
    if dev.name == name then return dev.id end
  end
  return nil
end

function QuickApp:turnOn()
  self:updateProperty("value", true)
  print("qa3: turned on")
  local qa4 = findDevice("qa-four")
  if qa4 then
    fibaro.call(qa4, "notify", "qa3 is on")
  end
end

function QuickApp:turnOff()
  self:updateProperty("value", false)
  print("qa3: turned off")
end
