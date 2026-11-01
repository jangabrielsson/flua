-- mock-panels.lua — a shareable emulation module: require() it from any
-- QA and the registered endpoints answer that QA's api.* calls (offline
-- sim only). Built-in routes always win; these paths are not built in.
--
--   require("mock-panels")   -- in onInit (or at the top of the QA file)
--
-- Handlers run as QA callbacks on the pump: the full api surface works
-- inside them (post refreshState events via _FLUA.postRefreshEvent etc.).
-- Routes die with the QA (exit/restart clears them).

local M = {}

api.registerEndpoint("GET", "/panels/sprinklers/{id}", function(req)
  -- {id} params are strings; the query arrives parsed, e.g. {zone={"2"}}
  return { id = tonumber(req.params.id), name = "Sprinklers " .. req.params.id }, 200
end)

api.registerEndpoint("POST", "/panels/sprinklers/{id}/actions/run", function(req)
  _FLUA.postRefreshEvent{
    type = "DevicePropertyUpdatedEvent",
    data = { id = 900001, property = "state", newValue = "running" },
  }
  return { started = true, minutes = req.body and req.body.minutes or 5 }, 200
end)

return M
