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

-- ------------------------------------------------------- message sanitation
-- Lua strings are byte strings; the Python bridge decodes them strictly as
-- UTF-8 (lupa runtime encoding), so any message field carrying invalid UTF-8
-- would raise inside _PY.post and take the whole process down. Messages are
-- JSON-compatible by contract, so enforce that here: strings that are not
-- valid UTF-8 are hex-escaped (\xNN for non-ASCII bytes, NUL and DEL) instead
-- of crossing the bridge raw. Rebuilds tables so keys are covered too.
local function sanitizeMsg(v)
  local tv = type(v)
  if tv == "string" then
    local ok, n = pcall(utf8.len, v, 1, -1, false)
    if ok and n then
      return v
    end
    local out, m = {}, 0
    for i = 1, #v do
      local b = string.byte(v, i)
      if b >= 0x80 or b == 0x00 or b == 0x7F then
        m = m + 1
        out[m] = string.format("\\x%02X", b)
      else
        m = m + 1
        out[m] = string.char(b)
      end
    end
    return table.concat(out)
  elseif tv == "table" then
    local t = {}
    for k, val in pairs(v) do
      t[sanitizeMsg(k)] = sanitizeMsg(val)
    end
    return t
  end
  return v
end

local _PY_post = _PY.post
_PY.post = function(msg) _PY_post(sanitizeMsg(msg)) end

-- ------------------------------------------------------------------ logging
-- Log lines print directly from Python (_PY.log): writing to stdout never
-- touches Lua state, so it is safe at any call depth — including inside
-- debugger-stepped code, where the message pump is frozen — and output is
-- always immediate instead of queueing behind the pump. The text is
-- sanitized first (see above): it crosses the bridge as a plain string.
local function postLog(level, ...)
  local parts = {}
  for i = 1, select("#", ...) do
    parts[i] = tostring(select(i, ...))
  end
  _PY.log(level, sanitizeMsg(table.concat(parts, "\t")))
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
function _FLUA.setTimeout(fn, ms, qa)
  ms = ms or 0
  local id = register(fn)
  -- qa attributes the timer to a QA; nil = runtime/untracked
  _PY.post{ type = "setTimeout", id = id, delay = ms, qa = qa }
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

function _FLUA.setInterval(fn, ms, qa)
  nextId = nextId + 1
  local id = nextId
  local function tick()
    if not intervals[id] then return end
    xpcall(fn, traceback)
    if intervals[id] then
      intervals[id] = _FLUA.setTimeout(tick, ms, qa)
    end
  end
  intervals[id] = _FLUA.setTimeout(tick, ms, qa)
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
-- HC3 semantics: exit() terminates the QA that called it (each QA is its own
-- process on the HC3; flua runs them cooperatively, so the engine cancels
-- that QA's timers and keeps the others running). With no qaId the call came
-- from runtime code and stops the engine itself.
function _FLUA.exit(code, qaId)
  _PY.post{ type = "exit", code = code or 0, qa = qaId }
end

-- --------------------------------------------------------------------- json
-- HC3-compatible json, global like on the HC3: json.encode/json.decode plus
-- json.util.InitArray (array marking, see lua/json.lua). Backed by Python's
-- stdlib json through _PY.
json = require("json")
_FLUA.json = json

-- --------------------------------------------------------------- debugger
-- The VS Code mobdebug extension (alexeymelnichuk.lua-mobdebug) launches the
-- interpreter with `-l package -e "<bootstrap>"` where the bootstrap prepends
-- the extension's lua dir to package.path and calls
-- `require'vscode-mobdebug'.start(...)`. The extension's bundled mobdebug.lua
-- is incompatible with Lua 5.5 (it predates const variables), so pin both
-- module names to flua's own copy, loaded by absolute path: preload wins over
-- package.path, so the injected dir can never shadow it.
local function loadRuntimeMobdebug()
  local chunk = loadfile(_PY.runtime_dir .. "/mobdebug.lua")
  return chunk and chunk() or nil
end
package.preload["mobdebug"] = loadRuntimeMobdebug
package.preload["vscode-mobdebug"] = loadRuntimeMobdebug

-- mobdebug startup, plua-style: opt-in from the CLI (--debugger PORT or
-- MOBDEBUG_PORT), started before the QAs run so a listening IDE (the VS Code
-- mobdebug extension) can attach. Failures are non-fatal: without an IDE the
-- program just runs.
function _FLUA.startDebugger(host, port)
  local ok, mobdebug = pcall(require, "mobdebug")
  if not ok then
    print("Warning: mobdebug failed: " .. tostring(mobdebug))
    return
  end
  mobdebug.yieldtimeout = 0.5  -- 500ms timeout for yield operations

  -- Freeze virtual time while the debugger blocks waiting for commands:
  -- wrap mobdebug.connect so the raw socket's blocking receives notify the
  -- engine clock first. While paused at a breakpoint the asyncio pump stops,
  -- so Lua timers stop too -- time stands still until the debugger resumes.
  local real_connect = mobdebug.connect
  mobdebug.connect = function(dhost, dport)
    local sock, serr = real_connect(dhost, dport)
    if sock then
      local real_receive = sock.receive
      sock.receive = function(self, pattern, ...)
        if self._timeout ~= 0 then  -- blocking wait, not a probe
          _PY.note_debugger_pause()
        end
        return real_receive(self, pattern, ...)
      end
    end
    return sock, serr
  end

  local ok2, err = pcall(function()
    mobdebug.start(host or "localhost", port or 8172)
    mobdebug.on()
    mobdebug.coro()
  end)
  if ok2 then
    _FLUA.mobdebug = mobdebug
  else
    print("Warning: mobdebug failed: " .. tostring(err))
  end
end

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
-- gets its own setTimeout/setInterval wrappers that attribute their timers
-- to the QA (tracked engine-side, one source of truth).
--
-- Before the QA code loads, the runtime libraries quickapp.lua and
-- fibaro.lua are loaded into the QA's environment (quickapp -> fibaro),
-- together with the HC3-style globals (__fibaro_add_debug_message,
-- printErr) and a minimal api stub. This gives QA code QuickApp,
-- QuickAppBase, fibaro, plugin, hub and the fibaro print behavior without
-- leaking any of it into other QAs. (quickapp.lua defines its own class
-- function per QA; plua needed a separate class.lua for its global
-- emulator code, flua does not.)

-- plua-compatible table helpers used by quickapp.lua
table.copy = function(t)
  if type(t) ~= "table" then return t end
  local r = {}
  for k, v in pairs(t) do r[k] = v end
  return r
end
table.member = function(name, list)
  for _, v in ipairs(list or {}) do
    if v == name then return true end
  end
  return false
end

local qaInstances = {}  -- qaId -> QuickApp instance (registered by the bootstrap)
-- net.HTTPClient response routing: net.lua registers one handler per QA.
_FLUA.netHandlers = {}
-- mqtt.* response routing: mqtt.lua registers one handler per QA.
_FLUA.mqttHandlers = {}

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

local function installQaGlobals(env)
  -- HC3-style globals for QA code. On the real HC3 the runtime provides
  -- these as Lua globals; flua installs them into each QA's environment.
  function env.__fibaro_add_debug_message(tag, msg, level)
    -- print directly with the real level (the global print always logs as
    -- "info"), so the engine's log handler can colorize by level
    _PY.log(level, sanitizeMsg(formatLogLine(tag, level, msg)))
  end

  -- HC3 REST API. Offline, _PY.api dispatches to the simulated HC3
  -- (running QAs plus seeded state); online mode will route to the real
  -- HC3. Contract: (data, status) — data is nil on errors.
  local function apiCall(method)
    return function(url, body) return _PY.api(method, url, body) end
  end
  env.api = {
    get = apiCall("GET"),
    post = apiCall("POST"),
    put = apiCall("PUT"),
    delete = apiCall("DELETE"),
  }
  -- api.hc3: the direct-HC3 namespace (fibaro.callhc3). Offline it is the
  -- same simulated HC3 as api.
  env.api.hc3 = {
    get = apiCall("GET"),
    post = apiCall("POST"),
    put = apiCall("PUT"),
    delete = apiCall("DELETE"),
  }
end

local qaRuntimeLibs = { "quickapp.lua", "fibaro.lua", "net.lua", "mqtt.lua" }

local function installQaLibs(env)
  installQaGlobals(env)
  -- the runtime dir is an absolute fact from Python, not the first
  -- package.path entry: QA code may rewrite package.path (the VS Code
  -- mobdebug extension's -e bootstrap prepends its own lua dir)
  local dir = _PY.runtime_dir
  for _, name in ipairs(qaRuntimeLibs) do
    local chunk, err = loadfile(dir .. "/" .. name, "bt", env)
    if not chunk then
      print("Error loading " .. name .. ": " .. tostring(err))
      _FLUA.exit(1)
      return
    end
    local ok, err2 = pcall(chunk)
    if not ok then
      print("Error running " .. name .. ": " .. tostring(err2))
      print(debug.traceback(nil, 2))
      _FLUA.exit(1)
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
    return _FLUA.setTimeout(fn, ms, qaId)
  end
  env.clearTimeout = _FLUA.clearTimeout
  env.setInterval = function(fn, ms)
    return _FLUA.setInterval(fn, ms, qaId)
  end
  env.clearInterval = _FLUA.clearInterval
  env.exit = function(code)  -- HC3: terminates this QA
    return _FLUA.exit(code, qaId)
  end
  return env
end

local function qaEnvFor(qaId)
  local env = _FLUA.makeQaEnv(qaId)
  setmetatable(env, {
    __index = _G,
    __newindex = function(t, k, v) rawset(t, k, v) end,
  })
  return env
end

local function bootstrapQa(env, qaId, config)
  -- The QA code is loaded: construct its QuickApp instance from the QA's
  -- config. Construction runs QuickApp:onInit (quickapp.lua does that in
  -- __init, like the HC3 at startup). The instance is registered here (the
  -- engine's Python-side directory is filled via the qaLoaded message).
  -- Names are not required to be unique; ids are always assigned by the
  -- engine (unique, starting at 5000) — like the real HC3, user code can
  -- not pick its own id.
  local cfg = config or {}
  -- The Python side registered this QA as a device already (type skeleton
  -- from the device catalog plus config); build the instance from that, so
  -- the Lua side sees the same device the API serves. Fallback covers
  -- bootstrap without a registration (should not happen in practice).
  local dev = _PY.device_for(qaId) or {
    id = qaId,
    name = cfg.name or ("QA" .. tostring(qaId)),
    type = cfg.type or "com.fibaro.binarySwitch",
    properties = cfg.properties or {},
  }
  local qa = env.QuickApp(dev)
  qaInstances[qaId] = qa
  return qa
end

-- Shared QA bootstrap: own _FLUA (qaId/config/arg) + runtime libs + load +
-- run the chunk + construct the QuickApp instance. Used by both the CLI
-- start path (timer-wrapped) and dynamic loading (eager, via startQA).
local function startQaInEnv(env, qaId, config, args, loader, sourceName)
  -- each QA gets its own _FLUA: qaId, config and arg are per-QA (stable in
  -- deferred reads); the rest of the API (timers, async, json, qa(...),
  -- exit, ...) is the shared engine table, found through __index
  env._FLUA = setmetatable({
    qaId = qaId,
    config = config or {},
    arg = args,
  }, { __index = _FLUA })
  installQaLibs(env)  -- class/quickapp/fibaro into this QA, before its code
  local chunk, err = loader()
  if not chunk then
    print("Error loading " .. tostring(sourceName) .. ": " .. tostring(err))
    _FLUA.exit(1)
    return
  end
  local ok, err2 = pcall(chunk)
  if not ok then
    print("Error:", err2)
    print(debug.traceback(nil, 2))
    _FLUA.exit(1)
    return
  end
  -- QA code loaded: construct the QuickApp instance (calls onInit)
  local bok, berr = pcall(bootstrapQa, env, qaId, config)
  if not bok then
    print("Error in bootstrap:", berr)
    print(debug.traceback(nil, 2))
    _FLUA.exit(1)
    return
  end
  _PY.post{ type = "qaLoaded", id = qaId }
end

local function runQa(env, qaId, config, args, loader, sourceName)
  -- run inside the QA's own (tracked) 0 ms timer, so it starts through the
  -- pump like everything else
  env.setTimeout(function()
    startQaInEnv(env, qaId, config, args, loader, sourceName)
  end, 0)
end

-- Multi-file QAs (--%%file:path,name): extra files load into the env in
-- declaration order BEFORE the main file. Shared by startQaFile, startQA
-- (dynamic loads) and restartQA.
local function loadExtraFiles(files, env)
  for _, f in ipairs(files or {}) do
    local chunk, err = loadfile(f.path, "bt", env)
    if not chunk then
      return nil, err
    end
    local ok, err2 = pcall(chunk)
    if not ok then
      print("Error in file " .. tostring(f.name) .. ": " .. tostring(err2))
      return nil, "failed to load " .. tostring(f.name)
    end
  end
  return true
end

function _FLUA.startQaFile(qaId, path, config, args)
  local env = qaEnvFor(qaId)
  runQa(env, qaId, config, args, function()
    local ok, err = loadExtraFiles(config and config.files, env)
    if not ok then return nil, err end
    return loadfile(path, "bt", env)
  end, path)
end

function _FLUA.startQaCode(qaId, code, config, args)
  local env = qaEnvFor(qaId)
  runQa(env, qaId, config, args, function()
    return load(code, "=(command line)", "t", env)
  end, "=(command line)")
end

function _FLUA.qa(qaId)
  return qaInstances[qaId]
end

-- Dynamic QA loading (dev/test convenience): install and run another QA
-- from a file (its --%% annotations are parsed Python-side) or from inline
-- code (written to a temp file first, then the file pipeline). Returns
-- (qaId, nil) or (nil, error message).
function _FLUA.loadQAfromFile(path)
  return _PY.load_qa_file(path)
end

function _FLUA.loadQAfromString(code)
  local path = _PY.qa_temp_file(code)
  return _FLUA.loadQAfromFile(path)
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

-- Device actions arrive through the pump (never synchronously from Python):
-- the api handler enqueues, the pump delivers, and the QA's own callAction
-- does method lookup + error containment (quickapp.lua).
local function qaForDevice(id)
  local qa = qaInstances[id]
  if qa then return qa end
  for _, main in pairs(qaInstances) do
    local child = main.childDevices and main.childDevices[id]
    if child then return child end
  end
  return nil
end

handlers.deviceAction = function(msg)
  local qa = qaForDevice(msg.id)
  if qa and type(qa.callAction) == "function" then
    qa:callAction(msg.action, table.unpack(msg.args or {}))
  elseif qa == nil then
    postLog("warning", "deviceAction for unknown device " .. tostring(msg.id))
  end
end

handlers.customEvent = function(msg)
  for _, qa in pairs(qaInstances) do
    local fn = qa.onCustomEvent
    if type(fn) == "function" then
      xpcall(function() fn(qa, msg.name) end, traceback)
    end
  end
end

-- Dynamically loaded QAs (loadQAfromFile/loadQAfromString) boot eagerly,
-- so a fibaro.call in the same callback that loaded them already reaches
-- the new instance.
handlers.startQA = function(msg)
  local env = qaEnvFor(msg.id)
  startQaInEnv(env, msg.id, msg.config or {}, msg.arg0, function()
    local ok, err = loadExtraFiles(msg.files, env)
    if not ok then return nil, err end
    return loadfile(msg.path, "bt", env)
  end, msg.path)
end

handlers.restartQA = function(msg)
  local env = qaEnvFor(msg.id)
  startQaInEnv(env, msg.id, msg.config or {}, msg.arg0, function()
    local ok, err = loadExtraFiles(msg.files, env)
    if not ok then return nil, err end
    return loadfile(msg.path, "bt", env)
  end, msg.path)
end

handlers.httpResult = function(msg)
  local h = _FLUA.netHandlers[msg.qa]
  if h then
    xpcall(function() h(msg) end, traceback)
  end
end

handlers.tcpResult = function(msg)
  local h = _FLUA.netHandlers[msg.qa]
  if h then
    xpcall(function() h(msg) end, traceback)
  end
end

handlers.udpResult = function(msg)
  local h = _FLUA.netHandlers[msg.qa]
  if h then
    xpcall(function() h(msg) end, traceback)
  end
end

handlers.wsEvent = function(msg)
  local h = _FLUA.netHandlers[msg.qa]
  if h then
    xpcall(function() h(msg) end, traceback)
  end
end

handlers.mqttEvent = function(msg)
  local h = _FLUA.mqttHandlers[msg.qa]
  if h then
    xpcall(function() h(msg) end, traceback)
  end
end

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