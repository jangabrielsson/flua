-- socket.lua — LuaSocket-compatible subset over flua's blocking Python sockets.
--
-- Covers what mobdebug needs: a tcp client (connect/settimeout/send/receive/
-- close) plus bind/accept for mobdebug.listen() server mode. receive() takes
-- "*l", "*a", or a byte count and returns LuaSocket conventions: data on
-- success, or nil, "timeout", partial / nil, "closed", partial.
--
-- NOTE: these calls block the main thread (and therefore the asyncio loop).
-- That is deliberate: while the debugger waits at a breakpoint, Lua timers
-- are frozen — time stops. See README "Debugging".

local _PY = _PY or {}

local socket = {
  _VERSION = "flua socket (LuaSocket-compatible subset)",
}

local tcp_mt = { __index = {} }
local server_mt = { __index = {} }

function tcp_mt.__index:connect(host, port)
  if self.closed then return nil, "socket closed" end
  local ok, res = _PY.tcp_connect(host, tonumber(port), self._timeout or 1.0)
  if not ok then return nil, res end
  self.conn_id = res
  if self._timeout then _PY.tcp_set_timeout(self.conn_id, self._timeout) end
  return 1
end

function tcp_mt.__index:settimeout(timeout)
  if self.conn_id then _PY.tcp_set_timeout(self.conn_id, timeout) end
  self._timeout = timeout
end

function tcp_mt.__index:send(data, i, j)
  if not self.conn_id then return nil, "closed" end
  local ok, res = _PY.tcp_write(self.conn_id, string.sub(data, i or 1, j or -1))
  if ok then return res end
  return nil, res
end

function tcp_mt.__index:receive(pattern, prefix)
  if not self.conn_id then return nil, "closed" end
  -- success: (true, data); failure: (false, err, partial) — LuaSocket shape
  local ok, data, partial = _PY.tcp_read(self.conn_id, pattern or "*l")
  if ok then
    local text = tostring(data)
    if prefix then return prefix .. text end
    return text
  end
  return nil, data, partial
end

function tcp_mt.__index:close()
  if self.conn_id then
    _PY.tcp_close(self.conn_id)
    self.conn_id = nil
  end
  self.closed = true
  return 1
end

function tcp_mt.__index:getsockname()
  if not self.conn_id then return nil, "closed" end
  local ok, ip, port = _PY.tcp_getsockname(self.conn_id)
  if ok then return ip, port end
  return nil, ip
end

function tcp_mt.__tostring(self)
  return "tcp{client}"
end

function socket.tcp()
  return setmetatable({ conn_id = nil, _timeout = nil, closed = false }, tcp_mt)
end

function socket.bind(host, port)
  local ok, res = _PY.tcp_bind(host, tonumber(port))
  if not ok then return nil, res end
  return setmetatable({ server_id = res, closed = false }, server_mt)
end

function server_mt.__index:accept()
  if self.closed then return nil, "socket closed" end
  local ok, res = _PY.tcp_accept(self.server_id)
  if not ok then return nil, res end
  local client = socket.tcp()
  client.conn_id = res
  return client
end

function server_mt.__index:close()
  if self.server_id then
    _PY.tcp_close(self.server_id)
    self.server_id = nil
  end
  self.closed = true
  return 1
end

function server_mt.__index:getsockname()
  if not self.server_id then return nil, "closed" end
  local ok, ip, port = _PY.tcp_getsockname(self.server_id)
  if ok then return ip, port end
  return nil, ip
end

function server_mt.__tostring(self)
  return "tcp{server}"
end

return socket
