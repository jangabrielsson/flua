--%%name:AlarmEndpoint
--%%type:com.fibaro.genericDevice
--%%description:"Simulated alarm system endpoints (bundled with flua)"

-- The HC3 alarm system as a bundled sim device:
--   local alarm = _FLUA.loadSimDevice("alarmEndpoint")
--
-- The /alarms/v1/* endpoints serve THREE kinds of partitions, like the
-- real HC3:
--   * built-in partitions (the sim's seeded state — partition 1 "Home")
--   * user-deployed com.fibaro.alarmPartition QAs
--   * partitions created through POST /alarms/v1/partitions
--
--   local p, s = api.post("/alarms/v1/partitions", { name = "Garage" })
--   api.post("/alarms/v1/partitions/" .. p.id .. "/actions/arm")
--   local part = _FLUA.loadSimDevice("alarmPartition", { "name:Garden" })
--   api.post("/alarms/v1/partitions/" .. part .. "/actions/arm")
--
-- Deployed QAs are tracked live: a RefreshStateSubscriber maintains the
-- cache from DeviceCreated/Removed/PropertyUpdated events, so partitions
-- appear when their QA starts, disappear when it stops, and their
-- arm/disarm/breach changes (however they happen — the endpoint, a scene,
-- a direct fibaro.call) emit the alarm events: AlarmPartitionArmedEvent /
-- AlarmPartitionBreachedEvent (partition-level) and HomeArmStateChanged /
-- HomeDisarmStateChanged / HomeBreachedEvent (home-level).
--
-- Handler rule: from inside an override handler, api.* calls hit the
-- BUILT-IN routes (user routes match nothing for the suspended QA), so the
-- built-in partition list and arm/disarm stay authoritative for built-ins.

local PARTITION_TYPE = "com.fibaro.alarmPartition"

-- partitions created through POST /alarms/v1/partitions (this device owns them)
local created = {}
-- deployed com.fibaro.alarmPartition QAs: id -> partition DTO (live cache)
local qaCache = {}

local function emitArmed(id, armed)
  _FLUA.postRefreshEvent{
    type = "AlarmPartitionArmedEvent",
    data = { partitionId = tonumber(id), armed = armed },
  }
  _FLUA.postRefreshEvent{
    type = armed and "HomeArmStateChangedEvent" or "HomeDisarmStateChangedEvent",
    data = { newValue = true },
  }
end

local function emitBreached(id, breached)
  _FLUA.postRefreshEvent{
    type = "AlarmPartitionBreachedEvent",
    data = { partitionId = tonumber(id), breached = breached },
  }
  _FLUA.postRefreshEvent{
    type = "HomeBreachedEvent",
    data = { breached = breached },
  }
end

local function emitModified(id)
  _FLUA.postRefreshEvent{
    type = "AlarmPartitionModifiedEvent",
    data = { partitionId = tonumber(id) },
  }
end

local function cachePartition(dev)
  local props = dev.properties or {}
  qaCache[dev.id] = {
    id = dev.id,
    name = dev.name,
    armed = props.armed == true,
    breached = props.alarm == true,  -- the alarm property is the breach state
  }
end

local function builtinPartitions()
  local parts, status = api.get("/alarms/v1/partitions")  -- the built-in list
  return status == 200 and parts or {}
end

local function qaPartitions()
  local out = {}
  for _, p in pairs(qaCache) do out[#out + 1] = p end
  return out
end

local function createdPartitions()
  local out = {}
  for _, p in pairs(created) do out[#out + 1] = p end
  return out
end

local function allPartitions()
  local merged = {}
  for _, p in ipairs(builtinPartitions()) do merged[#merged + 1] = p end
  for _, p in ipairs(createdPartitions()) do merged[#merged + 1] = p end
  for _, p in ipairs(qaPartitions()) do merged[#merged + 1] = p end
  table.sort(merged, function(a, b) return a.id < b.id end)
  return merged
end

local function nextPartitionId()
  local id = 1
  for _, p in ipairs(allPartitions()) do id = math.max(id, p.id + 1) end
  return id
end

local function findPartition(id)
  id = tonumber(id)
  if not id then return nil end
  if created[id] then return created[id] end
  if qaCache[id] then return qaCache[id] end
  for _, p in ipairs(builtinPartitions()) do
    if p.id == id then return p end
  end
  return nil
end

-- arm/disarm one partition: created -> own state, QA -> the QA's action
-- (its delays/events; the subscriber emits the alarm events), built-in ->
-- the built-in route (state.alarms; this handler emits the events).
-- Returns (nil, status).
local function armPartition(id)
  id = tonumber(id)
  if created[id] then
    created[id].armed = true
    created[id].breached = false
    emitArmed(id, true)
    return nil, 202
  end
  if qaCache[id] then
    fibaro.call(id, "arm")
    return nil, 202
  end
  local _, status = api.post("/alarms/v1/partitions/" .. id .. "/actions/arm")
  if status ~= 202 then return nil, 404 end
  emitArmed(id, true)
  return nil, 202
end

local function disarmPartition(id)
  id = tonumber(id)
  if created[id] then
    created[id].armed = false
    emitArmed(id, false)
    return nil, 202
  end
  if qaCache[id] then
    fibaro.call(id, "disarm")
    return nil, 202
  end
  local _, status = api.delete("/alarms/v1/partitions/" .. id .. "/actions/disarm")
  if status ~= 202 then return nil, 404 end
  emitArmed(id, false)
  return nil, 202
end

function QuickApp:onInit()
  self:debug("alarm endpoints up, id", self.id)

  -- live tracking of deployed alarmPartition QAs: start/remove/state changes
  local sub = RefreshStateSubscriber()
  sub:subscribe(
    function(e)
      local t = e.type or ""
      return t == "DeviceCreatedEvent"
        or t == "DeviceRemovedEvent"
        or (t == "DevicePropertyUpdatedEvent" and qaCache[tonumber(e.data and e.data.id)] ~= nil)
    end,
    function(e)
      local d = e.data or {}
      local id = tonumber(d.id)
      local t = e.type
      if t == "DeviceCreatedEvent" then
        local dev = api.get("/devices/" .. id)
        if dev and dev.type == PARTITION_TYPE then
          cachePartition(dev)
        end
      elseif t == "DeviceRemovedEvent" then
        qaCache[id] = nil
      else -- DevicePropertyUpdatedEvent on a cached QA partition
        local p = qaCache[id]
        local prop, value = d.property, d.newValue
        if prop == "armed" and p.armed ~= (value == true) then
          p.armed = value == true
          emitArmed(id, p.armed)
        elseif prop == "alarm" and p.breached ~= (value == true) then
          p.breached = value == true
          emitBreached(id, p.breached)
        end
      end
    end
  )
  sub:run()
  -- adopt the QAs that are already running (the subscriber covers the rest)
  for _, dev in ipairs(api.get("/devices") or {}) do
    if dev.type == PARTITION_TYPE and qaCache[dev.id] == nil then
      cachePartition(dev)
    end
  end
  _FLUA.keepAlive()

  -- the merged list (built-in + created + deployed alarmPartition QAs)
  api.registerEndpoint("GET", "/alarms/v1/partitions", function()
    return allPartitions(), 200
  end, true)

  api.registerEndpoint("GET", "/alarms/v1/partitions/breached", function()
    local out = {}
    for _, p in ipairs(allPartitions()) do
      if p.breached then out[#out + 1] = p end
    end
    return out, 200
  end, true)

  api.registerEndpoint("GET", "/alarms/v1/partitions/{id}", function(req)
    local p = findPartition(req.params.id)
    return p or nil, p and 200 or 404
  end, true)

  -- create a partition the HC3 way (no built-in route exists for this)
  api.registerEndpoint("POST", "/alarms/v1/partitions", function(req)
    local body = req.body or {}
    local id = nextPartitionId()
    created[id] = {
      id = id,
      name = body.name or ("Partition " .. id),
      armed = false,
      breached = false,
      armDelay = body.armDelay or 1000,
      breachDelay = body.breachDelay or 0,
    }
    emitModified(id)
    return created[id], 200
  end)

  -- delete a created partition (built-in and QA partitions stay owned by
  -- their owners)
  api.registerEndpoint("DELETE", "/alarms/v1/partitions/{id}", function(req)
    local id = tonumber(req.params.id)
    if id and created[id] then
      created[id] = nil
      emitModified(id)
      return nil, 204
    end
    return nil, 404
  end)

  -- arm/disarm one partition (any kind)
  api.registerEndpoint("POST", "/alarms/v1/partitions/{id}/actions/arm", function(req)
    return armPartition(req.params.id)
  end, true)

  api.registerEndpoint("DELETE", "/alarms/v1/partitions/{id}/actions/disarm", function(req)
    return disarmPartition(req.params.id)
  end, true)

  -- arm/disarm all partitions of every kind
  api.registerEndpoint("POST", "/alarms/v1/partitions/actions/arm", function()
    for _, p in ipairs(allPartitions()) do armPartition(p.id) end
    return nil, 202
  end, true)

  api.registerEndpoint("DELETE", "/alarms/v1/partitions/actions/disarm", function()
    for _, p in ipairs(allPartitions()) do disarmPartition(p.id) end
    return nil, 202
  end, true)
end

-- breach / clear a created partition (the HC3's alarm property equivalent)
function QuickApp:breached(id, state)
  id = tonumber(id)
  if not created[id] then
    self:warning("no created partition", tostring(id))
    return
  end
  created[id].breached = state == true
  emitBreached(id, created[id].breached)
end
