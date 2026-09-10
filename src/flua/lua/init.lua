-- flua runtime: cooperative timers + message dispatch.
--
-- _PY is installed by Python (bindings.py); this script adds the Lua half of
-- the message protocol.
--
-- Inbound (Lua -> Python):  _PY.post({...})       -- append-only, never blocks
-- Outbound (Python -> Lua): _PY.dispatch(batch)   -- the ONLY entry point
-- Python uses to call into Lua. Called from the pump task, never nested.

local _PY = _PY or {}

-- The engine's Lua-side API lives in _FLUA (config, timers, async, exit,
-- QA support). The bare globals below are convenience aliases for it.
-- _PY holds the pure Python bridge (post, now, vtime, tcp_*, ...) and is
-- not meant for user code.
_FLUA = {}
_FLUA.version = _PY.version()

-- ----------------------------------------------------------------- registry
-- One-shot callback registry. The id doubles as the timer id on the Python
-- side: _PY.post{type="setTimeout", id=N, ...} schedules timer N, and the
-- resulting timerExpired message runs callbacks[N] exactly once.
local callbacks = {}
local nextId = 0

local function register(fn)
  nextId = nextId + 1
  callbacks[nextId] = fn
  return nextId
end

-- ------------------------------------------------------------------ logging
local function postLog(level, ...)
  local parts = {}
  for i = 1, select("#", ...) do
    parts[i] = tostring(select(i, ...))
  end
  _PY.post{ type = "log", level = level, text = table.concat(parts, "\t") }
end

print = function(...) postLog("info", ...) end
_FLUA.print = print

-- --------------------------------------------------------- virtual time
-- os.time/os.clock/os.date follow the engine's virtual clock, so timer math
-- stays consistent with absolute-time computations in every mode: debugger
-- pauses freeze time, --speed accelerates it, --instant jumps it forward
-- with every fired timer.
local real_os_time, real_os_date, real_os_clock = os.time, os.date, os.clock

os.time = function(tbl)
  if tbl == nil then return _PY.vtime() end
  return real_os_time(tbl)
end

os.date = function(fmt, t)
  if fmt == nil then return real_os_date("%c", math.floor(_PY.vtime())) end
  if t == nil then return real_os_date(fmt, math.floor(_PY.vtime())) end
  return real_os_date(fmt, t)
end

os.clock = function() return _PY.vclock() end

local function traceback(err)
  postLog("error", tostring(err))
  postLog("error", debug.traceback(nil, 2))
end

-- ------------------------------------------------------------------- timers
function _FLUA.setTimeout(fn, ms)
  ms = ms or 0
  local id = register(fn)
  _PY.post{ type = "setTimeout", id = id, delay = ms }
  return id
end
setTimeout = _FLUA.setTimeout

function _FLUA.clearTimeout(id)
  if callbacks[id] then
    callbacks[id] = nil
    _PY.post{ type = "clearTimeout", id = id }
  end
end
clearTimeout = _FLUA.clearTimeout

-- setInterval is built on setTimeout chaining (cooperative, like JS).
local intervals = {} -- id -> timeout id currently scheduled

function _FLUA.setInterval(fn, ms)
  nextId = nextId + 1
  local id = nextId
  local function tick()
    if not intervals[id] then return end
    xpcall(fn, traceback)
    if intervals[id] then
      intervals[id] = setTimeout(tick, ms)
    end
  end
  intervals[id] = setTimeout(tick, ms)
  return id
end
setInterval = _FLUA.setInterval

function _FLUA.clearInterval(id)
  local timeoutId = intervals[id]
  if timeoutId then
    clearTimeout(timeoutId)
    intervals[id] = nil
  end
end
clearInterval = _FLUA.clearInterval

-- --------------------------------------------------------------------- exit
function _FLUA.exit(code)
  _PY.post{ type = "exit", code = code or 0 }
end
exit = _FLUA.exit

-- -------------------------------------------------------------------- async
-- Coroutine-based async/await over the message model.
--
--   async.run(function()
--     local v = async.await(function(finish)
--       setTimeout(function() finish(42) end, 50)
--     end)
--     print(v)  -- 42, delivered when the timer fires
--   end)
--
-- The body runs as a coroutine. async.await(worker) suspends it and calls
-- worker(finish); when the async work completes it calls finish(...) and the
-- coroutine resumes with those values. Suspension happens through
-- setTimeout-style messages, so the pump keeps running while any number of
-- coroutines wait. Errors go to onError (default: printed with a traceback,
-- like timer callback errors).

_FLUA.async = {}
async = _FLUA.async  -- global alias
local A = _FLUA.async -- internal handle for the definitions below

function A.await(worker)
  return coroutine.yield(worker)
end

function A.wait(ms)
  return A.await(function(finish)
    setTimeout(function() finish() end, ms)
  end)
end

function A.run(fn, onError)
  local co = coroutine.create(fn)
  local function step(...)
    if coroutine.status(co) == "dead" then return end
    local ok, yielded = coroutine.resume(co, ...)
    if not ok then
      local err = tostring(yielded)
      if onError then
        onError(err)
      else
        postLog("error", "async: " .. err)
        postLog("error", debug.traceback(co, nil, 2))
      end
      return
    end
    if coroutine.status(co) == "dead" then return end
    if type(yielded) ~= "function" then
      local err = "async: expected a function(finish) awaitable, got " .. type(yielded)
      if onError then onError(err) else postLog("error", err) end
      return
    end
    -- hand finish to the worker; it resumes us later (or synchronously)
    yielded(step)
  end
  step()
end

-- ---------------------------------------------------------------------- qa
-- Every Lua file is a QuickApp. Each QA runs in its own environment: same
-- Lua state, but global writes land in a per-QA table (__newindex), while
-- reads fall through to the shared runtime globals (__index). Each QA also
-- gets its own setTimeout/setInterval wrappers that track which timers
-- belong to which QA.
--
-- Before the QA code loads, the runtime libraries class.lua, quickapp.lua
-- and fibaro.lua are loaded into the QA's environment (class -> quickapp ->
-- fibaro), together with a minimal fibaro.plua stub. This gives QA code
-- QuickApp, QuickAppBase, fibaro, plugin, hub and the fibaro print behavior
-- without leaking any of it into other QAs.

-- plua-compatible table helpers used by quickapp.lua
table.copy = function(t)
  local r = {}
  for k, v in pairs(t or {}) do r[k] = v end
  return r
end
table.member = function(name, list)
  for _, v in ipairs(list or {}) do
    if v == name then return true end
  end
  return false
end

local qaTimers = {}     -- qaId -> { timerId -> true }
local qaIntervals = {}  -- qaId -> { intervalId -> true }
local qaInstances = {}  -- qaId -> QuickApp instance (via fibaro.plua:registerQAGlobally)

-- HC3-style log lines for fibaro.debug/trace/warning/error, colored like
-- plua: gray date and tag, level in its color (DEBUG=green, TRACE=cyan,
-- WARNING=orange, ERROR=red), plain message.
--   [dd.mm.yyyy][hh:mm:ss][LEVEL  ][TAG]: message
-- The timestamp comes from os.date, which reads the engine's virtual clock.
-- Colors are embedded here (whole line), gated by _PY.color_enabled().
local LEVEL_COLORS = {
  DEBUG = "\27[32m",   -- green
  TRACE = "\27[36m",   -- cyan
  WARNING = "\27[33m", -- orange/yellow
  ERROR = "\27[31;1m", -- red (bold)
}
local LOG_GRAY, LOG_RESET = "\27[37m", "\27[0m"

local function formatLogLine(tag, level, msg)
  local date = os.date("[%d.%m.%Y][%H:%M:%S]")
  if _PY.color_enabled() then
    return string.format(
      "%s%s%s[%-7s]%s[%s]: %s%s",
      LOG_GRAY, date,
      LEVEL_COLORS[level] or "", tostring(level),
      LOG_GRAY, tostring(tag), tostring(msg), LOG_RESET
    )
  end
  return string.format("%s[%-7s][%s]: %s", date, tostring(level), tostring(tag), tostring(msg))
end

local function installPluaStub(env)
  -- Minimal fibaro.plua until the full emulator lands. Enough for prints,
  -- QuickApp construction, and error reporting.
  local stub = { formatOutput = tostring, lib = {} }
  -- plua-compat: quickapp.lua calls this from QuickAppBase:__init, but the
  -- engine's bootstrap registers the instance itself (qaInstances) — the
  -- Python side owns the QA directory.
  function stub.registerQAGlobally() end
  function stub.lib.__fibaro_add_debug_message(tag, msg, level)
    -- post directly with the real level (the global print always logs as
    -- "info"), so the engine's log handler can colorize by level
    _PY.post{ type = "log", level = level, text = formatLogLine(tag, level, msg) }
  end
  env.printErr = function(e) print("Error: " .. tostring(e)) end
  env.fibaro = env.fibaro or {}
  env.fibaro.plua = stub

  -- Minimal HC3 REST API until the real client lands. Returns empty data
  -- and warns, so QuickApp construction works (child lookup etc.).
  local function apiStub(method, url)
    print(string.format("[FLUA][WARNING] api.%s('%s') not implemented yet", method, tostring(url)))
    return {}
  end
  env.api = {
    get = function(url) return apiStub("get", url) end,
    post = function(url) return apiStub("post", url) end,
    put = function(url) return apiStub("put", url) end,
    delete = function(url) return apiStub("delete", url) end,
  }
end

local qaRuntimeLibs = { "class.lua", "quickapp.lua", "fibaro.lua" }

local function installQaLibs(env)
  installPluaStub(env)
  local dir = package.path:match("^([^;]+)/%?%.lua")
  for _, name in ipairs(qaRuntimeLibs) do
    local chunk, err = loadfile(dir .. "/" .. name, "bt", env)
    if not chunk then
      print("Error loading " .. name .. ": " .. tostring(err))
      exit(1)
      return
    end
    local ok, err2 = pcall(chunk)
    if not ok then
      print("Error running " .. name .. ": " .. tostring(err2))
      print(debug.traceback(nil, 2))
      exit(1)
      return
    end
  end
end

local function qaTrack(set, qaId, id)
  local s = set[qaId]
  if not s then s = {}; set[qaId] = s end
  s[id] = true
end

local function qaUntrack(set, qaId, id)
  local s = set[qaId]
  if s then s[id] = nil end
end

function _FLUA.makeQaEnv(qaId)
  local env = {}
  env.setTimeout = function(fn, ms)
    local id
    id = setTimeout(function()
      qaUntrack(qaTimers, qaId, id)
      fn()
    end, ms)
    qaTrack(qaTimers, qaId, id)
    return id
  end
  env.clearTimeout = function(id)
    clearTimeout(id)
    qaUntrack(qaTimers, qaId, id)
  end
  env.setInterval = function(fn, ms)
    local id = setInterval(fn, ms)
    qaTrack(qaIntervals, qaId, id)
    return id
  end
  env.clearInterval = function(id)
    clearInterval(id)
    qaUntrack(qaIntervals, qaId, id)
  end
  return env
end

function _FLUA.qaTimerCount(qaId)
  local count = 0
  for _ in pairs(qaTimers[qaId] or {}) do count = count + 1 end
  for _ in pairs(qaIntervals[qaId] or {}) do count = count + 1 end
  return count
end

local function qaEnvFor(qaId, config, args)
  local env = _FLUA.makeQaEnv(qaId)
  env.qaId = qaId
  env.config = config or {}
  env.arg = args
  setmetatable(env, {
    __index = _G,
    __newindex = function(t, k, v) rawset(t, k, v) end,
  })
  return env
end

-- Merge the QA's config into the shared _FLUA.config table, so values like
-- --%%name: are visible engine-wide (the last loaded QA wins). The QA's own
-- `config` remains its stable per-QA copy.
local function mergeConfig(config)
  for k, v in pairs(config or {}) do
    _FLUA.config[k] = v
  end
end

local function bootstrapQa(env)
  -- The QA code is loaded: construct its QuickApp instance from the QA's
  -- config. Construction runs QuickApp:onInit (quickapp.lua does that in
  -- __init, like the HC3 at startup). The instance is registered here (the
  -- engine's Python-side directory is filled via the qaLoaded message).
  -- Names are not required to be unique; ids are always assigned by the
  -- engine (unique, starting at 5000) — like the real HC3, user code can
  -- not pick its own id.
  local cfg = env.config
  local dev = {
    id = env.qaId,
    name = cfg.name or ("QA" .. tostring(env.qaId)),
    type = cfg.type or "com.fibaro.binarySwitch",
    properties = cfg.properties or {},
  }
  local qa = env.QuickApp(dev)
  qaInstances[env.qaId] = qa
  return qa
end

local function runQa(env, config, loader, sourceName)
  -- run inside the QA's own (tracked) 0 ms timer, so it starts through the
  -- pump like everything else
  env.setTimeout(function()
    mergeConfig(config) -- the QA's config becomes visible engine-wide now
    installQaLibs(env)  -- class/quickapp/fibaro into this QA, before its code
    local chunk, err = loader()
    if not chunk then
      print("Error loading " .. tostring(sourceName) .. ": " .. tostring(err))
      exit(1)
      return
    end
    local ok, err2 = pcall(chunk)
    if not ok then
      print("Error:", err2)
      print(debug.traceback(nil, 2))
      exit(1)
      return
    end
    -- QA code loaded: construct the QuickApp instance (calls onInit)
    local bok, berr = pcall(bootstrapQa, env)
    if not bok then
      print("Error in bootstrap:", berr)
      print(debug.traceback(nil, 2))
      exit(1)
      return
    end
    _PY.post{ type = "qaLoaded", id = env.qaId }
  end, 0)
end

function _FLUA.startQaFile(qaId, path, config, args)
  local env = qaEnvFor(qaId, config, args)
  runQa(env, config, function()
    return loadfile(path, "bt", env)
  end, path)
end

function _FLUA.startQaCode(qaId, code, config, args)
  local env = qaEnvFor(qaId, config, args)
  runQa(env, config, function()
    return load(code, "=(command line)", "t", env)
  end, "=(command line)")
end

function _FLUA.qa(qaId)
  return qaInstances[qaId]
end

-- ----------------------------------------------------------------- dispatch
-- Python -> Lua entry point: batch is an array of messages.
local handlers = {}

handlers.timerExpired = function(msg)
  local fn = callbacks[msg.id]
  if fn then
    callbacks[msg.id] = nil -- one-shot
    xpcall(fn, traceback)
  else
    postLog("warning", "timerExpired for unknown id " .. tostring(msg.id))
  end
end

-- Future message types register here, e.g.:
--   handlers.httpResult = function(msg) ... end

function _FLUA.dispatch(batch)
  for i = 1, #batch do
    local msg = batch[i]
    local h = handlers[msg.type]
    if h then
      xpcall(function() h(msg) end, traceback)
    else
      postLog("warning", "no Lua handler for message type " .. tostring(msg.type))
    end
  end
end
