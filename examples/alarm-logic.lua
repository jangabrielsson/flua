-- alarm-logic.lua — the "prototype in Lua, promote to Python later" pattern:
-- overrides the BUILT-IN alarm partition endpoints with real behavior —
-- arming with an exit delay, refreshState events at each transition.
--
--   require("alarm-logic")   -- in onInit; the module owns the partition
--
-- Override routes win over built-ins (built-ins still win over normal
-- routes). Handlers run as QA callbacks: setTimeout schedules the delayed
-- transitions on the virtual clock (instant in --instant mode),
-- _FLUA.postRefreshEvent emits what subscribers see. A handler calling
-- its own endpoint falls through to the built-in/404 (no recursion).

local M = {}

M.exitDelayMs = 2000  -- the arming delay (tune per partition)
M.armDelayMs = 1000  -- the arming delay (tune per partition)

-- the module owns the partition state: id -> {armed, arming, breached}
local partitions = {}
local ID = 1

local function shape(id)
  if not id then id = ID; ID = ID + 1 end
  local p = partitions[id] or {}
  p = {
    id = id,
    name = p.name or "Alarm",
    armed = p.armed or false,
    arming = p.arming or false,
    breached = p.breached or false,
    breachDelay = p.breachDelay or M.exitDelayMs,
    armDelay = p.armDelay or M.armDelayMs,
    devices = p.devices or {},
    lastActionAt = p.lastActionAt or 0,
  }
  partitions[id] = p -- store the shaped partition back into the table
  return p
end

local function emit(id, property, newValue)
  _FLUA.postRefreshEvent{
    type = "DevicePropertyUpdatedEvent",
    data = { id = id, property = property, newValue = newValue },
  }
end

api.registerEndpoint("POST", "/alarms/v1/partitions", function(req)
  local data = req.body or {}
  local p = shape()
  p.name = data.name or "Alarm"
  return p, 201
end, true)

api.registerEndpoint("GET", "/alarms/v1/partitions/{id}", function(req)
  local id = tonumber(req.params.id)
  local p,code = partitions[id] and shape(id) or nil, partitions[id] and 200 or 404
  return p, code
end, true)

api.registerEndpoint("GET", "/alarms/v1/partitions", function()
  local list = {}
  for id in pairs(partitions) do
    list[#list + 1] = shape(id)
  end
  table.sort(list, function(a, b) return a.id < b.id end)
  return list, 200
end, true)

api.registerEndpoint("POST", "/alarms/v1/partitions/{id}/actions/arm", function(req)
  local id = tonumber(req.params.id)
  local p = partitions[id]
  if not p then return nil, 404 end
  p.arming = true
  p.armed = false
  emit(id, "armed", false)  -- the HC3 panels show the arming phase
  setTimeout(function()
    p.arming = false
    p.armed = true
    emit(id, "armed", true)  -- armed after the exit delay
  end, p.armDelay)
  return nil, 202
end, true)

api.registerEndpoint("DELETE", "/alarms/v1/partitions/{id}/actions/disarm", function(req)
  local id = tonumber(req.params.id)
  local p = partitions[id]
  if not p then return nil, 404 end
  p.arming = false
  p.armed = false
  emit(id, "armed", false)
  return nil, 202
end, true)


-- a liveness marker the CALLER QAs can poll before relying on the panel
-- (the owner's routes register during its boot; callers wait for this)
api.registerEndpoint("GET", "/vendor/alarm-panel/ready", function()
  return { ready = true }, 200
end)

return M
