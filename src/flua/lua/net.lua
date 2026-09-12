-- net: HTTPClient and TCPSocket for QAs, HC3-style.
--
-- Both classes post requests to the Python engine (message types below),
-- where they run in worker threads (urllib / a dedicated socket pool);
-- results come back through the pump as messages routed to this QA by id.
-- Callbacks run inside this QA's environment, so closures over QA state
-- work like timers do.
local qaId = _FLUA.qaId

local requests = {}    -- id -> {success = fn, error = fn} (http)
local tcpRequests = {} -- id -> {sock = TCPSocket instance, kind = str, cb = table}
local nextId = 0

local function callbackErr(err)
  print("[net] callback error: " .. tostring(err))
end

-- ------------------------------------------------------------------ HTTP
-- net.HTTPClient: asynchronous HTTP.
--
--   local client = net.HTTPClient()
--   client:request("https://...", {
--     options = { method = "POST", headers = {...}, data = "...", timeout = 10 },
--     success = function(resp) ... resp.status, resp.data, resp.headers ... end,
--     error = function(err) ... end,
--   })
--
-- Like the HC3: any completed HTTP exchange (including 4xx/5xx) reaches
-- success; only transport failures (DNS, refused, timeout) reach error.
local HTTPClient = {}
setmetatable(HTTPClient, HTTPClient)  -- the class is its own metatable (__call + __index)
HTTPClient.__index = HTTPClient
HTTPClient.__call = function()
  return setmetatable({}, HTTPClient)
end

function HTTPClient:request(url, params)
  params = params or {}
  local options = params.options or {}
  local id = nextId
  nextId = id + 1
  requests[id] = { success = params.success, error = params.error }
  _PY.post{
    type = "httpRequest",
    id = id,
    qa = qaId,
    url = tostring(url),
    method = options.method or "GET",
    headers = options.headers,
    data = options.data,
    timeout = options.timeout,
  }
  return id
end

local function handleHttpResult(msg)
  local cb = requests[msg.id]
  if not cb then return end
  requests[msg.id] = nil
  local fn = msg.error and cb.error or cb.success
  if not fn then return end
  xpcall(function()
    if msg.error then
      fn(msg.error)
    else
      fn({ status = msg.status, data = msg.data or "", headers = msg.headers or {} })
    end
  end, callbackErr)
end

-- ------------------------------------------------------------------ TCP
-- net.TCPSocket: asynchronous TCP client with the documented HC3 API.
-- Operations run in Python worker threads (never blocking the pump) and
-- their callbacks arrive through the pump.
--
--   local sock = net.TCPSocket({timeout = 10000})  -- ms, optional
--   sock:connect("10.0.0.10", 4998, {
--     success = function() ... end,
--     error = function(message) ... end,
--   })
--   sock:send(data, {success = function() ... end, error = fn})
--   sock:read({success = function(data) ... end, error = fn})          -- a data package
--   sock:readUntil("\n", {success = function(data) ... end, error = fn})
--   sock:close()
local TCPSocket = {}
setmetatable(TCPSocket, TCPSocket)
TCPSocket.__index = TCPSocket
TCPSocket.__call = function(_, options)
  local timeout = options and options.timeout or 10000  -- ms (docs example)
  return setmetatable({ _conn = nil, _timeout = tonumber(timeout) / 1000 }, TCPSocket)
end

local function tcpRequest(sock, kind, cb, msg)
  local id = nextId
  nextId = id + 1
  tcpRequests[id] = { sock = sock, kind = kind, cb = cb or {} }
  msg.id = id
  msg.qa = qaId
  _PY.post(msg)
  return id
end

function TCPSocket:connect(ip, port, callbacks)
  tcpRequest(self, "connect", callbacks, {
    type = "tcpConnect",
    host = tostring(ip),
    port = tonumber(port),
    timeout = self._timeout,
  })
end

function TCPSocket:send(data, callbacks)
  tcpRequest(self, "send", callbacks, {
    type = "tcpSend",
    conn = self._conn,
    data = tostring(data),
  })
end

function TCPSocket:read(callbacks)
  tcpRequest(self, "read", callbacks, { type = "tcpRead", conn = self._conn })
end

function TCPSocket:readUntil(delimiter, callbacks)
  tcpRequest(self, "read", callbacks, {
    type = "tcpRead",
    conn = self._conn,
    delimiter = tostring(delimiter),
  })
end

function TCPSocket:close()
  if self._conn then
    _PY.tcp_close(self._conn)
    self._conn = nil
  end
end

-- ------------------------------------------------------------------ UDP
-- net.UDPSocket: asynchronous UDP datagram socket, HC3-style. The
-- constructor binds an ephemeral socket synchronously (bind is instant);
-- sendTo/receive run in worker threads with pump-delivered callbacks.
--
--   local udp = net.UDPSocket({broadcast = true, timeout = 5000})  -- ms
--   udp:sendTo(data, "255.255.255.255", 44444, {success = fn, error = fn})
--   udp:receive({success = function(data) ... end, error = fn})  -- one datagram
--   udp:close()
local UDPSocket = {}
setmetatable(UDPSocket, UDPSocket)
UDPSocket.__index = UDPSocket
UDPSocket.__call = function(_, options)
  options = options or {}
  local timeout = options.timeout or 10000  -- ms (docs example)
  local ok, conn, err = _PY.udp_open(not not options.broadcast, tonumber(timeout) / 1000)
  if not ok then
    error("net.UDPSocket: " .. tostring(conn), 2)
  end
  return setmetatable({ _conn = conn }, UDPSocket)
end

function UDPSocket:sendTo(data, ip, port, callbacks)
  tcpRequest(self, "send", callbacks, {
    type = "udpSend",
    conn = self._conn,
    data = tostring(data),
    ip = tostring(ip),
    port = tonumber(port),
  })
end

function UDPSocket:receive(callbacks)
  tcpRequest(self, "receive", callbacks, { type = "udpReceive", conn = self._conn })
end

function UDPSocket:close()
  if self._conn then
    _PY.udp_close(self._conn)
    self._conn = nil
  end
end

local function handleTcpResult(msg)
  local entry = tcpRequests[msg.id]
  if not entry then return end
  tcpRequests[msg.id] = nil
  if msg.ok then
    if entry.kind == "connect" then entry.sock._conn = msg.conn end
    local fn = entry.cb.success
    if fn then xpcall(function() fn(msg.data) end, callbackErr) end
  else
    local fn = entry.cb.error
    if fn then xpcall(function() fn(msg.err) end, callbackErr) end
  end
end

-- ------------------------------------------------------------------ dispatch
-- One handler per QA; the shared dispatch (init.lua) routes by the
-- request's qa attribution.
_FLUA.netHandlers[qaId] = function(msg)
  if msg.type == "httpResult" then
    handleHttpResult(msg)
  elseif msg.type == "tcpResult" then
    handleTcpResult(msg)
  elseif msg.type == "udpResult" then
    handleTcpResult(msg)  -- same entry shape: {sock, kind, cb}
  end
end

net = { HTTPClient = HTTPClient, TCPSocket = TCPSocket, UDPSocket = UDPSocket }