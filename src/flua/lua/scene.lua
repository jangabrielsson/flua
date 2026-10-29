-- scene.lua — the HC3 Lua scene runner (flua extension).
--
-- A QA with --%%scene:true runs as a scene: the file carries the scene's
-- declarations (a global COND table) above a marker line and the actions
-- below it — everything after the marker is top-level Lua, re-run on every
-- scene start, exactly like the HC3 re-runs a scene's code:
--
--   COND = { ... }                     -- declarations
--   -- ===== SCENE ACTIONS =====
--   fibaro.debug(_sceneId, "trigger:", json.encode(sourceTrigger))
--
-- Phase 1: boot parses the declarations only (actions do NOT run at boot);
-- manual execute runs the actions with sourceTrigger = {type="manual"}.
-- Phase 2: the conditions evaluator. refreshEvents are transformed to
-- sourceTrigger tables (lib/sourcetrigger.lua) and posted through the pump
-- (sceneTrigger messages); date triggers arm virtual-clock timers that post
-- their own sourceTrigger at the fire time. On each event every scene
-- checks whether any trigger leaf matches, evaluates the whole tree against
-- current state, and runs the actions when it holds (duration = the tree
-- must still hold at now+duration).

local SCENE_MARKER = "SCENE ACTIONS"

local function readFile(path)
  local fh, err = io.open(path, "r")
  if not fh then
    error("cannot open scene file " .. tostring(path) .. ": " .. tostring(err), 2)
  end
  local source = fh:read("*a")
  fh:close()
  return source
end

local function declarations(source)
  local lines, n = {}, 0
  for line in (source .. "\n"):gmatch("(.-)\r?\n") do
    if line:find(SCENE_MARKER) then
      return table.concat(lines, "\n")
    end
    n = n + 1
    lines[n] = line
  end
  error(
    "scene file is missing the actions marker line (-- ===== " .. SCENE_MARKER .. " =====", 2
  )
end

-- parse-only load at boot: COND lands in the QA env, actions never run;
-- then the runner activates (trigger registration needs the parsed COND).
-- The source is cached here: runScene re-runs it per trigger, and the file
-- itself may be gone by then (loadQAfromString scenes live in temp files
-- that are deleted once the QA loads).
local sceneSource = nil

function _FLUA.sceneDeclarations(path)
  sceneSource = readFile(path)
  local chunk, err = load(declarations(sceneSource), "@" .. path .. "[declarations]", "t", _G)
  if not chunk then error(err, 2) end
  chunk()
  if _FLUA.config.scene then activateScene() end
  return function() end -- the loader runs this; nothing to do at boot
end

-- every scene start: the whole file runs again (COND re-assigns, actions
-- execute), with sourceTrigger and _sceneId in scope — the HC3 semantics
local function runScene(trigger)
  sourceTrigger = trigger or { type = "manual", property = "execute" }
  local chunk, err = load(sceneSource, "@" .. tostring(_FLUA.arg[0] or "scene"), "t", _G)
  if not chunk then
    print("Error loading scene " .. tostring(_FLUA.arg[0]) .. ": " .. tostring(err))
    return
  end
  local ok, err2 = pcall(chunk)
  if not ok then
    print("Error in scene:", err2)
    print(debug.traceback(nil, 2))
  end
end

-- ---------------------------------------------------------- phase 2: evaluator

local sourcetrigger = (function()
  local chunk = loadfile(_PY.runtime_dir .. "/lib/sourcetrigger.lua", "bt", _G)
  return chunk and chunk() or nil
end)()

-- ---- operators ----------------------------------------------------------

local function opMatches(op, actual, wanted)
  if op == "anyValue" then return true end
  if op == "==" then return actual == wanted end
  if op == "!=" then return actual ~= wanted end
  local a, b = tonumber(actual), tonumber(wanted)
  if a == nil or b == nil then return false end
  if op == ">" then return a > b end
  if op == ">=" then return a >= b end
  if op == "<" then return a < b end
  if op == "<=" then return a <= b end
  return false
end

-- ---- cron / date --------------------------------------------------------

-- the HC3 cron tuple: {minute, hour, day-of-month, month, day-of-week,
-- year}; day-of-week is 1=Monday .. 7=Sunday (Lua's wday is 1=Sunday)
local function nowTuple(at)
  local t = os.date("*t", at or os.time())
  local dow = (t.wday - 1) % 7 + 1
  return {
    tostring(t.min), tostring(t.hour), tostring(t.day),
    tostring(t.month), tostring(dow), tostring(t.year),
  }
end

local function cronFieldMatch(pattern, current)
  if pattern == nil or pattern == "*" then return true end
  for item in tostring(pattern):gmatch("[^,]+") do
    if item == tostring(current) then return true end
  end
  return false
end

local function cronMatches(cond, now)
  for i = 1, 6 do
    if not cronFieldMatch(cond[i], now[i]) then return false end
  end
  return true
end

-- a comparable timestamp: '*' fields take the CURRENT value (so
-- match>= {0,9,*,*,*,*} means "from 9:00 today"); the dow field is a
-- constraint, applied by cronCompare separately
local function tupleTimestamp(tup, now)
  local y = tup[6] == "*" and tonumber(now[6]) or tonumber(tup[6])
  local mo = tup[4] == "*" and tonumber(now[4]) or tonumber(tup[4])
  local d = tup[3] == "*" and tonumber(now[3]) or tonumber(tup[3])
  local h = tup[2] == "*" and tonumber(now[2]) or tonumber(tup[2])
  local mi = tup[1] == "*" and tonumber(now[1]) or tonumber(tup[1])
  return ((y * 100 + mo) * 100 + d) * 10000 + h * 100 + mi
end

local function cronCompare(op, cond, now)
  if not cronFieldMatch(cond[5], now[5]) then return false end
  local a = tupleTimestamp(now, now)
  local b = tupleTimestamp(cond, now)
  if op == ">" then return a > b end
  if op == ">=" then return a >= b end
  if op == "<" then return a < b end
  if op == "<=" then return a <= b end
  return false
end

local function intervalMatches(cond, now)
  -- value = {date = tuple, interval = seconds}; fires at date + k*interval
  local start = tupleTimestamp(cond.date, now)
  local nowTs = tupleTimestamp(now, now)
  local interval = tonumber(cond.interval) or 0
  if interval <= 0 or nowTs < start then return false end
  return (nowTs - start) % interval == 0
end

local function sunTime(property)
  local dev = api.get("/devices/1")
  local hour = dev and dev.properties and dev.properties[property .. "Hour"]
  if type(hour) ~= "string" then return nil end
  local h, m = hour:match("^(%d+):(%d+)$")
  return h and m and tonumber(h) * 3600 + tonumber(m) * 60 or nil
end

-- ---- leaf evaluation (against current state) -----------------------------

local function evalLeaf(leaf, event, now)
  local t = leaf.type
  if t == "device" then
    local dev = api.get("/devices/" .. leaf.id)
    local v = dev and dev.properties and dev.properties[leaf.property]
    return opMatches(leaf.operator, v, leaf.value)
  elseif t == "global-variable" then
    return opMatches(leaf.operator, fibaro.getGlobalVariable(leaf.property), leaf.value)
  elseif t == "custom-event" then
    return event and event.type == "custom-event" and event.name == leaf.property
  elseif t == "alarm" then
    if leaf.property == "homeArmed" or leaf.property == "homeBreached" then
      local partitions = api.get("/alarms/v1/partitions")
      for _, p in ipairs(partitions or {}) do
        if leaf.property == "homeArmed" and not opMatches(leaf.operator, p.armed, leaf.value) then
          return false
        end
        if leaf.property == "homeBreached" and not opMatches(leaf.operator, p.breached, leaf.value) then
          return false
        end
      end
      return true
    end
    local p = api.get("/alarms/v1/partitions/" .. leaf.id)
    return opMatches(leaf.operator, p and p[leaf.property], leaf.value)
  elseif t == "weather" then
    local w = api.get("/weather")
    return opMatches(leaf.operator, w and w[leaf.property], leaf.value)
  elseif t == "profile" then
    local profiles = api.get("/profiles")
    for _, p in ipairs(profiles or {}) do
      if p.active then return opMatches(leaf.operator, p.id, leaf.value) end
    end
    return false
  elseif t == "location" then
    return event and event.type == "location" and event.id == leaf.id
      and event.property == leaf.property and opMatches(leaf.operator, event.value, leaf.value)
  elseif t == "se-start" then
    return event and event.type == "se-start"
  elseif t == "date" then
    if leaf.property == "cron" then
      local op = leaf.operator
      if op == "match" then return cronMatches(leaf.value, now) end
      if op == "matchInterval" then return intervalMatches(leaf.value, now) end
      local cmp = op:match("^match([<>]=?)$")
      if cmp then return cronCompare(cmp, leaf.value, now) end
      return false
    elseif leaf.property == "sunrise" or leaf.property == "sunset" then
      -- a filter: true at the moment the sun trigger fires (minute-granular)
      local t = sunTime(leaf.property)
      if not t then return false end
      local secs = os.date("*t").hour * 3600 + os.date("*t").min * 60 + os.date("*t").sec
      return math.abs(secs - (t + tonumber(leaf.value or 0) * 60)) < 60
    end
  end
  return false
end

local function evalTree(node, event, now)
  if node.type then return evalLeaf(node, event, now) end
  if node.operator == "any" then
    for _, c in ipairs(node.conditions or {}) do
      if evalTree(c, event, now) then return true end
    end
    return false
  end
  for _, c in ipairs(node.conditions or {}) do
    if not evalTree(c, event, now) then return false end
  end
  return true
end

-- ---- trigger collection --------------------------------------------------

-- each isTrigger leaf becomes a trigger entry; the dispatcher checks whether
-- an incoming event matches any entry, then evaluates the whole tree
local function collectTriggers(node, out)
  if node.type then
    if node.isTrigger then
      if node.type == "date" and node.operator ~= nil
        and node.operator:match("^match[<>]=?$") then
        print("flua: date trigger " .. tostring(node.operator)
          .. " is filters-only (the HC3 recommends against it) — ignored as a trigger")
      else
        out[#out + 1] = node
      end
    end
    return
  end
  for _, c in ipairs(node.conditions or {}) do
    collectTriggers(c, out)
  end
end

local function triggerMatches(leaf, event)
  local t = leaf.type
  if t == "device" then
    -- duration leaves trigger on ANY change of the property (the scene must
    -- re-check when the value stops matching, so the duration can be cut)
    local any = leaf.duration and leaf.duration > 0 or leaf.operator == "anyValue"
    return event and event.type == "device" and event.id == leaf.id
      and event.property == leaf.property
      and (any or opMatches(leaf.operator, event.value, leaf.value))
  elseif t == "global-variable" then
    return event and event.type == "global-variable" and event.name == leaf.property
  elseif t == "custom-event" then
    return event and event.type == "custom-event" and event.name == leaf.property
  elseif t == "alarm" then
    return event and event.type == "alarm" and event.property == leaf.property
      and (leaf.id == nil or event.id == leaf.id)
  elseif t == "weather" then
    return event and event.type == "weather" and event.property == leaf.property
  elseif t == "profile" then
    return event and event.type == "profile" and event.property == leaf.property
  elseif t == "location" then
    return event and event.type == "location" and event.id == leaf.id
      and event.property == leaf.property
  elseif t == "se-start" then
    return event and event.type == "se-start"
  elseif t == "date" then
    -- date triggers fire through their own timers: the event IS the trigger
    return event and event.type == "date" and event.property == leaf.property
  end
  return false
end

-- ---- date trigger scheduling ----------------------------------------------

local function nextCronFire(cond)
  -- the next minute-grid instant matching the cron tuple (within a year).
  -- The current minute counts only when now sits exactly on the grid
  -- (sec == 0); otherwise the scan starts at the next minute boundary.
  local now = os.time()
  local t0 = os.date("*t", now)
  -- a pinned YEAR outside the 366-day window can never match: bail out
  -- instead of scanning half a million minute-grid instants — the
  -- year-pinned cron idiom (a "never fire" date trigger in tests) would
  -- otherwise burn ~2 s of os.date calls on every scene boot
  if cond[6] and cond[6] ~= "*" then
    if not cronFieldMatch(cond[6], tostring(t0.year))
      and not cronFieldMatch(cond[6], tostring(t0.year + 1))
    then
      return nil
    end
  end
  local start = t0.sec == 0 and 0 or 60 - t0.sec
  for offset = start, 366 * 24 * 60 * 60, 60 do
    local t = os.date("*t", now + offset)
    local dow = (t.wday - 1) % 7 + 1
    local cand = {
      tostring(t.min), tostring(t.hour), tostring(t.day),
      tostring(t.month), tostring(dow), tostring(t.year),
    }
    if cronMatches(cond, cand) then return now + offset end
  end
  return nil
end

local function nextIntervalFire(cond)
  local now = os.time()
  local start = tupleTimestamp(cond.date, nowTuple())
  local interval = tonumber(cond.interval) or 0
  if interval <= 0 then return nil end
  if now < start then return start end
  local k = math.floor((now - start) / interval) + 1
  return start + k * interval
end

local function nextSunFire(leaf)
  local base = sunTime(leaf.property)
  if not base then return nil end
  local target = base + tonumber(leaf.value or 0) * 60
  local t = os.date("*t")
  local nowSecs = t.hour * 3600 + t.min * 60 + t.sec
  local today = os.time() - nowSecs + target  -- today at the target time
  return today > os.time() and today or today + 24 * 3600
end

local function armDateTrigger(leaf)
  local nextFire
  if leaf.operator == "match" then
    nextFire = nextCronFire(leaf.value)
  elseif leaf.operator == "matchInterval" then
    nextFire = nextIntervalFire(leaf.value)
  elseif leaf.property == "sunrise" or leaf.property == "sunset" then
    nextFire = nextSunFire(leaf)
  end
  if not nextFire then return end
  local delay = (nextFire - os.time()) * 1000
  if delay < 0 then delay = 0 end
  setTimeout(function()
    _PY.post{
      type = "sceneTrigger",
      event = {
        type = "date",
        property = leaf.property,
        value = leaf.value,
        -- the cond must be evaluated at the SCHEDULED fire instant, not at
        -- the possibly-late clock: the pump can fire the timer several
        -- virtual minutes past its deadline at high --speed, and a cron
        -- tested against that late time would miss its slot
        time = nextFire,
      },
    }
    armDateTrigger(leaf) -- re-arm for the next fire
  end, delay)
end

-- ---- the scene runner -----------------------------------------------------

local function makeRunner(cond)
  local triggers = {}
  collectTriggers(cond, triggers)
  local lastTrue = false
  local pending = nil
  local maxDuration = 0
  for _, leaf in ipairs(triggers) do
    local d = tonumber(leaf.duration) or 0
    if d > maxDuration then maxDuration = d end
  end

  local function evaluate(event)
    -- date triggers carry their scheduled fire time: the cond is tested
    -- at the instant the trigger meant, not at the clock read now
    local now = nowTuple(event and event.time)
    local holds = evalTree(cond, event, now)
    if holds then
      if maxDuration > 0 and not pending then
        pending = setTimeout(function()
          pending = nil
          if evalTree(cond, event, now) then
            lastTrue = false
            runScene(event)
          end
        end, maxDuration * 1000)
      end
      if maxDuration == 0 and not lastTrue then
        runScene(event)
      end
      lastTrue = true
    else
      if pending then
        clearTimeout(pending)
        pending = nil
      end
      lastTrue = false
    end
  end

  return {
    triggers = triggers,
    onRawEvent = function(event)

      if not sourcetrigger then return end
      sourcetrigger.refreshStateEvent2SourceTrigger(event, function(trigger)
        _PY.post{ type = "sceneTrigger", event = trigger }
      end)
    end,
    eval = function(event)
      for _, leaf in ipairs(triggers) do
        if triggerMatches(leaf, event) then
          evaluate(event)
          return
        end
      end
    end,
    run = runScene,
  }
end

activateScene = function()
  _sceneId = _FLUA.qaId
  local cond = COND
  if type(cond) ~= "table" or not cond.conditions then
    print("flua: scene " .. tostring(_FLUA.qaId)
      .. " has no COND table — manual execute still works")
    _FLUA.sceneRunners[_FLUA.qaId] = {
      run = runScene, eval = function() end, onRawEvent = function() end,
    }
    return
  end
  local runner = makeRunner(cond)
  for _, leaf in ipairs(runner.triggers) do
    if leaf.type == "date" then armDateTrigger(leaf) end
  end
  -- HC3 startup trigger: scenes with a se-start trigger run once at boot
  for _, leaf in ipairs(runner.triggers) do
    if leaf.type == "se-start" then
      _PY.post{ type = "sceneTrigger", event = { type = "se-start", property = "start", value = true } }
    end
  end
  _FLUA.sceneRunners[_FLUA.qaId] = runner
end
