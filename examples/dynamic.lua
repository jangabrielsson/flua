--%%name:dyn-loader
-- Example: dynamically load other QAs from inside a QA (dev/test style —
-- run only this file from VS Code and it brings up the QAs it needs).
-- Run with:
--   .venv/bin/flua examples/dynamic.lua
-- --------------- EOH ---------------
local fileQa, ferr = _FLUA.loadQAfromFile("examples/qa3.lua")
print("file load:", fileQa, ferr)

-- The inline QA carries its own --%% header; the EOH marker above keeps it
-- from leaking into this QA's config.
local strQa, serr = _FLUA.loadQAfromString([[
--%%name:inline-qa
function QuickApp:ping()
  print("string QA: pong")
end
]])
print("string load:", strQa, serr)

setTimeout(function()
  fibaro.call(fileQa, "turnOn") -- qa3 turns on (no qa-four around to notify)
  fibaro.call(strQa, "ping")
  local dev = api.get('/devices/'..strQa)
  print("inline name:", dev.name)
end, 100)
