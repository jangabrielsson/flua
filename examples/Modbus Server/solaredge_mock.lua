--%%name:SolarEdge Mock
--%%type:com.fibaro.binarySwitch
--%%useUiView:false
--%%var:port='1502'
--%%property:userDescription=Modbus TCP mock inverter (SunSpec) — buttons change the values the SolarEdge Live QA reads
--%%u:{label='label',text='label'}
--%%u:{button='btnSunUp',text='Sun +500W',onReleased='btnSunUp'}
--%%u:{button='btnSunDown',text='Sun -500W',onReleased='btnSunDown'}
--%%u:{button='btnGridExport',text='Grid: Export 1500W',onReleased='btnGridExport'}
--%%u:{button='btnGridImport',text='Grid: Import 500W',onReleased='btnGridImport'}
--%%u:{button='btnSocFull',text='Battery SOC 100%',onReleased='btnSocFull'}
--%%u:{button='btnSocHalf',text='Battery SOC 50%',onReleased='btnSocHalf'}
-- --------------- EOH ---------------
-- A SolarEdge inverter mock served by the generic Modbus server library.
-- Run it alongside the user's QA (unchanged) to see live readings:
--
--   flua "dev/SolarEdge Live/main.lua" "examples/Modbus Server/solaredge_mock.lua" \
--        -D "var:host='127.0.0.1'" --run-for 120
--
-- Press the mock's buttons (the UI viewer at http://127.0.0.1:PORT with
-- --ui PORT, or a driver QA via /plugins/callUIEvent) and the values the
-- SolarEdge Live QA shows change on its next poll.
--
-- Addresses below are 0-based SunSpec register numbers; the SolarEdge Live
-- QA's wire addresses (register - 40001) map onto them with base = 40000.

local server = require("modbus_server")
local solaredge = require("solaredge")
local helpers = server.helpers

local MAP = solaredge.map

-- SunSpec 0-based addresses the buttons touch (see solaredge.lua).
local AC_POWER = 40083   -- inverter AC power, W
local GRID_POWER = 40207 -- meter AC power, W (+ export / - import)
local BAT_POWER = 57715  -- battery power float, W (high word first)
local BAT_SOC = 57731    -- battery SOC float, %

local mock

local function decodeFloat(addr)
  -- big-endian float32 across two map words (high word first)
  local hi, lo = MAP[addr] or 0, MAP[addr + 1] or 0
  local b = hi * 65536 + lo
  local sign = (b & 0x80000000) ~= 0 and -1 or 1
  local exp = ((b >> 23) & 0xFF) - 127
  local mant = b & 0x7FFFFF
  if exp == -127 and mant == 0 then return 0 end
  mant = mant | 0x800000
  return sign * mant * 2 ^ (exp - 23)
end

local function render(label)
  local ac = MAP[AC_POWER] or 0
  local grid = MAP[GRID_POWER] or 0
  local temp = MAP[40103] or 0    -- the QA's temperature word (0-based)
  local status = MAP[40107] or 0  -- the QA's status word (0-based)
  label = label
    .. "SolarEdge mock — the QA reads these values:\n"
    .. ("AC power   : %d W\n"):format(ac)
    .. ("Grid power : %s%d W (%s)\n"):format(grid >= 0 and "+" or "", grid,
        grid >= 0 and "exporting" or "importing")
    .. ("Temperature: %.1f °C (status %s)\n"):format(temp / 10,
        status == 4 and "MPPT" or tostring(status))
    .. ("Battery SOC: %.0f%%\n"):format(decodeFloat(BAT_SOC))
    .. "\nPress a button to change a value."
  return label
end

function QuickApp:onInit()
  -- the listen port is a QA variable (default 1502, the SolarEdge Live QA's
  -- default) — override with -D var:port=N (0 = any free port). The map is
  -- served at BOTH wire bases — base 40000 (the QA's register - 40001
  -- convention) and altBase 0 (SunSpec base-0 addresses, e.g. 40083) —
  -- mirroring the real inverter, which answers both (verified on device).
  mock = server.serve(MAP, {
    port = tonumber(self:getVariable("port")) or 1502,
    base = 40000,
    altBase = 0,
  })
  print("SolarEdge mock listening on 127.0.0.1:" .. mock.srv.port)
  self:updateView("label", "text", render(""))
end

function QuickApp:refresh()
  self:updateView("label", "text", render(""))
end

function QuickApp:btnSunUp()
  MAP[AC_POWER] = (MAP[AC_POWER] or 0) + 500
  self:refresh()
end

function QuickApp:btnSunDown()
  MAP[AC_POWER] = math.max(0, (MAP[AC_POWER] or 0) - 500)
  self:refresh()
end

function QuickApp:btnGridExport()
  MAP[GRID_POWER] = 1500
  self:refresh()
end

function QuickApp:btnGridImport()
  MAP[GRID_POWER] = -500
  self:refresh()
end

function QuickApp:btnSocFull()
  local words = helpers.f32(100.0, false)
  MAP[BAT_SOC] = words[1]
  MAP[BAT_SOC + 1] = words[2]
  self:refresh()
end

function QuickApp:btnSocHalf()
  local words = helpers.f32(50.0, false)
  MAP[BAT_SOC] = words[1]
  MAP[BAT_SOC + 1] = words[2]
  self:refresh()
end
