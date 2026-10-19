--%%name:SolarEdge Modbus Mock (Lua)
-- A mock SolarEdge inverter built on flua's net.TCPServer — no Python.
-- Same register map as dev/solar_modbus_mock.py (per the SE SunSpec note).
-- The connection stays open across the demo's whole SunSpec walk (net.TCPServer
-- is persistent since the 0.1.63 net-server work); the handler buffers partial
-- frames per connection and replies per request, nil = no reply yet.

local MAP = {}
local function w(a, v) MAP[a] = v % 65536 end
local function ascii(a, s)
  local b = {s:byte(1, #s)}
  for i = 1, #b, 2 do w(a + (i - 1) / 2, b[i] * 256 + (b[i + 1] or 0)) end
end

ascii(40000, "SunS"); w(40002, 1); w(40003, 65)          -- signature + common

w(40069, 101); w(40070, 50)                              -- inverter model 101
w(40083, 2500); w(40084, 0)                              -- AC 2500 W, SF 0
w(40093, 0x000F); w(40094, 0x4240); w(40095, 0xFFFF)     -- energy u32, SF -1
w(40100, 2300); w(40101, 0)                              -- DC 2300 W

w(40121, 1); w(40122, 65); ascii(40155, "Export/Import") -- meter common + mode

w(40188, 203); w(40189, 55)                              -- meter model 203
w(40206, 0xFE0C); w(40210, 0)                            -- grid -500 W, SF 0
w(40226, 0x0007); w(40227, 0xA120)                       -- exported 500000 Wh
w(40234, 0x0001); w(40235, 0x86A0)                       -- imported 100000 Wh
w(40242, 0x0000)                                         -- energy SF 0
w(40245, 0xFFFF)                                         -- SunSpec end marker

-- battery floats, LOW word first (SE convention): 1200.5 = 0x44961000
w(57716, 0x1000); w(57717, 0x4496)
w(57732, 0x0000); w(57733, 0x42AA)                       -- SOC 85.0

local srv = net.TCPServer()
local bufs = {}  -- conn id -> pending bytes (frames may arrive split across reads)
srv:listen(1502, function(data, conn)
  local buf = (bufs[conn] or "") .. data
  if #buf < 8 then bufs[conn] = buf return nil end
  local length = string.unpack(">I2", buf, 5)
  if #buf < 6 + length then bufs[conn] = buf return nil end
  local frame = buf:sub(1, 6 + length)
  bufs[conn] = buf:sub(7 + length)
  local txid, proto, len, unit, func, addr, count = string.unpack(">I2I2I2BBI2I2", frame)
  if func ~= 3 then
    return string.pack(">I2I2I2BBB", txid, 0, 3, unit, 0x83, func)  -- exception
  end
  local body = {}
  for i = 0, count - 1 do
    body[#body + 1] = string.pack(">I2", MAP[addr + i] or 0)
  end
  local payload = table.concat(body)
  return string.pack(">I2I2I2BBB", txid, 0, 3 + #payload, unit, 3, #payload) .. payload
end)
print("MOCK listening on 127.0.0.1:" .. srv.port)
-- No keep-alive timer: the run ends when the client QA is done. (An
-- infinite setInterval here would hang every run and leak port 1502.)
