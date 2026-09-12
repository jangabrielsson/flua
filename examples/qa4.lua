--%%name:qa-four
-- Example QA pair: QAs calling each other over the HC3 REST API.
-- Run with:
--   .venv/bin/flua examples/qa3.lua examples/qa4.lua
-- This QA finds qa3 by name and drives it through fibaro.call; qa3 answers
-- through the "notify" action defined below.
local function findDevice(name)
  local devices = api.get('/devices?interface=quickApp')
  for _, dev in ipairs(devices) do
    if dev.name == name then return dev.id end
  end
  return nil
end

function QuickApp:notify(msg)
  print("qa4: got", msg)
end

setTimeout(function()
  local qa3 = findDevice("qa-three")
  if not qa3 then
    print("qa4: qa-three not found")
    return
  end
  print("qa4: turning qa-three on")
  fibaro.call(qa3, "turnOn")
  setTimeout(function()
    print("qa4: turning qa-three off")
    fibaro.call(qa3, "turnOff")
  end, 100)
end, 100)
