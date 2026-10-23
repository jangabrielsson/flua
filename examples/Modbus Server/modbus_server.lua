-- Modbus TCP mock server for flua QAs (built on net.TCPServer — no Python).
--
-- Serve a register map: map[address] = 16-bit word value. The client's PDU
-- address is translated to your map key with the base offset:
--
--   mapKey = base + pduAddress
--
--   base = 0      the map is keyed by raw Modbus PDU addresses (QAs that put
--                  the register number itself on the wire — the SolarEdge
--                  SunSpec convention used by the demo QA)
--   base = 40001  the map is keyed by classic "4xxxx" holding-register
--                  numbers (the default; QAs that subtract 40001)
--   base = 40000  the map is keyed by 0-based SunSpec register numbers
--                  (QAs with 1-based register numbers that subtract 40001 —
--                  the SolarEdge Live QA's convention)
--
-- Handled functions: 3 (read holding registers), 6 (write single), 16
-- (write multiple). Anything else gets an illegal-function exception.
-- Unknown addresses return 0 (a real device answers the whole span), so a
-- sparse map works; opts.zeroFill = false turns those into an illegal-data-
-- address exception instead.
--
-- Usage:
--   local server = require("modbus_server")
--   local srv = server.serve(MAP, { port = 1502, base = 40000 })
--   print("listening on 127.0.0.1:" .. srv.port)
--
-- The connection stays open across requests (the handler buffers partial
-- frames per connection); returning nil from the handler = no reply yet.

local ModbusServer = {}
ModbusServer.__index = ModbusServer

local function u16(v) return math.floor(v or 0) % 65536 end

local function packWords(words)
  local body = {}
  for _, w in ipairs(words) do body[#body + 1] = string.pack(">I2", u16(w)) end
  return table.concat(body)
end

local function exception(txid, unit, func, code)
  -- MBAP header (len = 3: unit + func|0x80 + code) + exception PDU
  return string.pack(">I2I2I2BBB", txid, 0, 3, unit, func + 0x80, code)
end

function ModbusServer.new(map, opts)
  opts = opts or {}
  return setmetatable({
    map = map or {},
    base = opts.base or 40001,
    altBase = opts.altBase,  -- optional second base: real SE devices serve
                            -- the map at BOTH the legacy and SunSpec bases
    port = opts.port or 1502,
    zeroFill = opts.zeroFill ~= false,
    onRead = opts.onRead,
    onWrite = opts.onWrite,
    verbose = opts.verbose == true,
    bufs = {},  -- conn id -> pending bytes (frames may arrive split)
    srv = nil,
  }, ModbusServer)
end

function ModbusServer:get(key) return self.map[key] or 0 end

function ModbusServer:lookup(pdu)
  -- resolve a wire address to a map value; with altBase set, an address
  -- that misses at the primary base is tried at the alternate one (the
  -- SolarEdge mock serves both the legacy low addresses and SunSpec 40000+)
  local v = self.map[self.base + pdu]
  if v == nil and self.altBase ~= nil then
    v = self.map[self.altBase + pdu]
  end
  return v
end

function ModbusServer:set(key, value)
  if self.onWrite then self.onWrite(key, u16(value)) end
  self.map[key] = u16(value)
end

function ModbusServer:handle(data, conn)
  local buf = (self.bufs[conn] or "") .. data
  if #buf < 8 then self.bufs[conn] = buf return nil end
  local length = string.unpack(">I2", buf, 5)
  if #buf < 6 + length then self.bufs[conn] = buf return nil end
  local frame = buf:sub(1, 6 + length)
  self.bufs[conn] = buf:sub(7 + length)
  local txid, proto, len, unit, func, addr, count =
    string.unpack(">I2I2I2BBI2I2", frame)
  if self.verbose then
    print(("[modbus] FC%d addr=%d count=%d unit=%d"):format(func, addr, count, unit))
  end
  if func == 3 then
    -- Modbus caps a read at 125 registers: the reply's byte count is one
    -- wire byte (max 255 = 127 registers). A client asking for more gets
    -- the first 125 of the span — a real device would answer an exception,
    -- which QAs like SolarEdge Live silently drop and then disconnect. The
    -- capped reply keeps them alive and shows the leading part of the map.
    if count > 125 then
      print(("[modbus] read for %d registers capped at 125 (Modbus wire limit)"):format(count))
      count = 125
    end
    local words = {}
    for i = 0, count - 1 do
      local v = self:lookup(addr + i)
      if not self.zeroFill and v == nil then
        return exception(txid, unit, func, 2)  -- illegal data address
      end
      words[#words + 1] = v or 0
    end
    if self.onRead then self.onRead(addr, count) end
    local payload = packWords(words)
    return string.pack(">I2I2I2BBB", txid, 0, 3 + #payload, unit, 3, #payload) .. payload
  elseif func == 6 then
    local value = string.unpack(">I2", frame, 11)
    self:set(self.base + addr, value)
    return string.pack(">I2I2I2BBI2I2", txid, 0, 6, unit, 6, addr, u16(value))
  elseif func == 16 then
    local words = {}
    for i = 0, count - 1 do
      words[#words + 1] = string.unpack(">I2", frame, 14 + i * 2)
    end
    for i = 0, count - 1 do self:set(self.base + addr + i, words[i + 1]) end
    return string.pack(">I2I2I2BBI2I2", txid, 0, 6, unit, 16, addr, u16(count))
  end
  return exception(txid, unit, func, 1)  -- illegal function
end

function ModbusServer:start()
  self.srv = net.TCPServer()
  self.srv:listen(self.port, function(data, conn) return self:handle(data, conn) end)
  return self
end

-- ------------------------------------------------------------------ helpers
-- Map-building helpers for device tables. u32/f32 are big-endian by default
-- (SunSpec); the StorEdge battery floats are the one LOW-word-first corner
-- case (lowFirst = true).

local function ascii_words(s)
  local b = { s:byte(1, #s) }
  local words = {}
  for i = 1, #b, 2 do
    words[#words + 1] = b[i] * 256 + (b[i + 1] or 0)
  end
  return words
end

ModbusServer.helpers = {
  u16 = u16,
  s16 = function(v) return u16(v) end,  -- negative values wrap like the wire
  u32 = function(v)
    return { u16(math.floor(v / 65536)), u16(v) }
  end,
  f32 = function(v, lowFirst)
    local hi, lo = string.unpack(">I2I2", string.pack(">f", v))
    if lowFirst then return { lo, hi } end
    return { hi, lo }
  end,
  ascii = ascii_words,
}

-- fill(map, baseKey, {word, word, ...}): write consecutive words.
function ModbusServer.fill(map, baseKey, words)
  for i, w in ipairs(words) do map[baseKey + i - 1] = u16(w) end
  return map
end

function ModbusServer.serve(map, opts)
  return ModbusServer.new(map, opts):start()
end

return ModbusServer
