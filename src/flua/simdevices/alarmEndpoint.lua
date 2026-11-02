--%%name:alarmEndpoint
--%%type:com.fibaro.genericDevice

-- alarmEndpoint.lua — the "prototype in Lua, promote to Python later" pattern:
-- overrides the BUILT-IN alarm partition endpoints with real behavior —
-- arming with an exit delay, refreshState events at each transition.
--
-- Override routes win over built-ins (built-ins still win over normal
-- routes). Handlers run as QA callbacks: setTimeout schedules the delayed
-- transitions on the virtual clock (instant in --instant mode),
-- _FLUA.postRefreshEvent emits what subscribers see. A handler calling
-- its own endpoint falls through to the built-in/404 (no recursion).

-- The endpoint handles 2 types of alarmPartitions
--  - Standard partitions created and deleted with the api/alarms/v1/partitions 
--  -- These have associated devices and are breached when device is breached
--  - User defined com.fibaro.alarmPartition QAs registered by the user
--  -- The user defines the behavior and devices for these partitions
--  -- However, we still manage their armed and breached states internally


local exitDelayMs = 2000  -- the arming delay (tune per partition)
local armDelayMs = 1000  -- the arming delay (tune per partition)

-- the module owns the partition state: id -> {armed, arming, breached}
local partitions = {}
local ID = 1

local function registerPartition(id)
  if not id then id = ID; ID = ID + 1 end
  local p = partitions[id] or {}
  p = {
    id = id,
    name = p.name or "Alarm",
    armed = p.armed or false,
    arming = p.arming or false,
    breached = p.breached or false,
    breachDelay = p.breachDelay or exitDelayMs,
    armDelay = p.armDelay or armDelayMs,
    devices = p.devices or {},
    lastActionAt = p.lastActionAt or 0,
  }
  partitions[id] = p
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
  registerPartition(data)
  return p, 201
end, true)

api.registerEndpoint("GET", "/alarms/v1/partitions/{id}", function(req)
  local id = tonumber(req.params.id)
  local p,code = partitions[id], partitions[id] and 200 or 404
  return p, code
end, true)

api.registerEndpoint("GET", "/alarms/v1/partitions", function()
  local list = {}
  for id in pairs(partitions) do
    list[#list + 1] = partitions[id]
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

---------------------------------------------------------------------------------------------
-- Track com.fibaro.alarmPartition devices started by the user
-- Register and remove when devices are created or removed
-- Also handle when partition is armed and disarmed, breached and safe
local Event = {}

local function qaPartition(id)
  local qa = api.get("/devices/" .. id)
  local armed = qa.armed == true
  local breached = qa.alarm == true
  local p = { id = id, name = qa.name, armed = armed, alarm = breached }
  registerPartition(p)
end

function Event.DeviceCreatedEvent(event)
  local id = tonumber(event.data.id)
  if id then qaPartition(id) end
end

function Event.DeviceRemovedEvent(event)
  local id = tonumber(event.data.id)
  if id then removeAlarm(id) end
end

function Event.DevicePropertyUpdatedEvent(event)
  local id = tonumber(event.data.id)
  local property = event.data.property
  local value = event.data.newValue
  if not id then return end
  if property == "armed" then armAlarm(id,value)
  elseif property == 'alarm' then alarm(id,value) end
end

function QuickApp:onInit()
  self:debug("alarmEndpoint initialized")
  local qaAlarms = api.get("/devices?type=com.fibaro.alarmPartition") or {}
  for _, device in ipairs(qaAlarms) do qaPartition(device.id) end
  
  -- RefreshStateSubscriber listeing for alarm partition state changes
  local events = RefreshStateSubscriber()
  local subscriber = RefreshStateSubscriber()
  subscriber:subscribe(
  function(event) return true end, 
  function(event) if Event[event.type] then Event[event.type](event) end end
  )
  subscriber:run()
end