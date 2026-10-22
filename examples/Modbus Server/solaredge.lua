-- SolarEdge SunSpec register map for the mock server — the register VALUES
-- a SolarEdge inverter reports, keyed at SunSpec base-0 register numbers
-- (the wire addresses). Source of truth: the SE technical note checked in
-- next to this file (sunspec-implementation-technical-note.pdf, v3.3):
-- its register tables list "Address (base 0)" and "(base 1)" columns, and
-- the base-0 column is the MODBUS Protocol Address that goes on the wire
-- ("the base Register ... is set to 40001 [base 1] or 40000 [base 0]").
--
-- The SolarEdge Live QA (SmartHomeEddy, forum topic 79101) numbers its
-- registers 1-based and subtracts 40001 when building the wire request, so
-- its AC power "40084" goes out as PDU 83. A read against a real inverter
-- (the QA author verified) shows the device serves AC power at BOTH bases:
-- PDU 40083 (the note's SunSpec base-0) and PDU 83 (the legacy SE protocol
-- layout — same model, low addresses). The mock serves the SunSpec map at
-- the QA's addresses (base = 40000, see solaredge_mock.lua), which is
-- equivalent for the inverter block; whether the legacy map also covers the
-- SunSpec METER models (wire 40188+) is unverified — worth a live check.
--
-- Layout (base-0, per the technical note):
--   40000..40068  SunSpec common block (ID, manufacturer, model, serial...)
--   40069..       inverter model 101/103 (AC power, energy, DC, temps...)
--   40121..       meter common block (DID=1) + "Export/Import" option string
--   40188..       meter model 203 (currents, power, exported/imported u32)
--   40245         0xFFFF SunSpec end marker
--   57715..       StorEdge battery floats (0xE173 area, SE low-word-first)
--
-- The default values are a plausible sunny-day snapshot; the mock QA's
-- buttons mutate them at runtime (see solaredge_mock.lua).

local helpers = require("modbus_server").helpers

local MAP = {}

local function w(addr, value) MAP[addr] = value % 65536 end
local function words(addr, list)
  for i, value in ipairs(list) do w(addr + i - 1, value) end
end
local function ascii(addr, s) words(addr, helpers.ascii(s)) end
local function u32(addr, value)
  words(addr, helpers.u32(value))
end

-- ------------------------------------------------------- SunSpec common
ascii(40000, "SunS")
w(40002, 1)      -- DID 1
w(40003, 65)     -- length 65
ascii(40004, "SolarEdge")
ascii(40020, "SE7600H")
ascii(40044, "4.13.12")
ascii(40052, "7F11223344")
w(40068, 1)      -- Modbus unit id

-- ------------------------------------------------- inverter model 103
w(40069, 103)    -- DID (matches the QA's default inverterType)
w(40070, 50)     -- length
w(40071, 50)     -- AC current total
w(40072, 16)     -- phase A
w(40073, 16)     -- phase B
w(40074, 16)     -- phase C
w(40075, 0)      -- current SF
w(40076, 3983)   -- voltage AB, SF -1 -> 398.3 V
w(40077, 3983)   -- voltage BC
w(40078, 3983)   -- voltage CA
w(40079, 2300)   -- voltage AN, SF -1 -> 230.0 V
w(40080, 2300)   -- voltage BN
w(40081, 2300)   -- voltage CN
w(40082, 0xFFFF) -- voltage SF -1
w(40083, 2500)   -- AC power W (SF 0) — the QA's mainRegister (1-based 40084)
w(40084, 0)      -- AC power SF
w(40085, 5000)   -- frequency, SF -2 -> 50.00 Hz
w(40086, 0xFFFE) -- frequency SF -2
w(40087, 2500)   -- VA
w(40088, 0)      -- VA SF
w(40089, 200)    -- VAR
w(40090, 0)      -- VAR SF
w(40091, 100)    -- PF, SF -2 -> 1.00
w(40092, 0xFFFE) -- PF SF
u32(40093, 1000000)  -- energy Wh (u32), SF -1 -> 100.0 kWh
w(40095, 0xFFFF)     -- energy SF -1
w(40096, 66)     -- DC current, SF -1 -> 6.6 A
w(40097, 0xFFFF) -- DC current SF
w(40098, 3484)   -- DC voltage, SF -1 -> 348.4 V
w(40099, 0xFFFF) -- DC voltage SF
w(40100, 2300)   -- DC power W
w(40101, 0)      -- DC power SF
w(40102, 450)    -- heat sink temp (SunSpec), SF -1 -> 45.0 C
-- The SolarEdge Live QA numbers its registers 1-based: its temperature
-- child (1-based 40104) reads THIS word as the value and 1-based 40107
-- (0-based 40106) as its scale factor — the QA's map sits one off the
-- SunSpec spec, so the mock follows the QA's wire addresses:
w(40103, 450)    -- QA "Heatsink temperature" value, with...
w(40106, 0xFFFF) -- ...SF -1 -> 45.00 C (also the events hi word: unused)
w(40104, 4)      -- SunSpec status (MPPT)
w(40105, 0)      -- vendor status
w(40107, 4)      -- QA "Operating status" value -> decodeEnum16 shows MPPT
u32(40108, 0)    -- vendor events (0-based spec position; unread by the QA)

-- --------------------------------------------------- meter common (DID 1)
w(40121, 1)      -- DID 1
w(40122, 65)     -- length
ascii(40123, "SolarEdge")
ascii(40139, "SE-WND-3Y400-MB-K1")
ascii(40155, "Export/Import")
ascii(40163, "1.0.0")
ascii(40171, "7F99887766")
w(40187, 1)      -- device address

-- ---------------------------------------------------- meter model 203
w(40188, 203)    -- DID
w(40189, 55)     -- length
w(40190, 22)     -- AC current total, SF -1 -> 2.2 A
w(40191, 7)      -- phase A
w(40192, 7)      -- phase B
w(40193, 7)      -- phase C
w(40194, 0xFFFF) -- current SF -1
w(40196, 2300)   -- voltage LN, SF -1 -> 230.0 V
w(40201, 0xFFFF) -- voltage SF
w(40205, 5000)   -- frequency, SF -2 -> 50.00 Hz
w(40206, 0xFFFE) -- frequency SF
w(40207, 1500)   -- AC power W (grid, SF 0) — +1500 = exporting
w(40211, 0)      -- power SF
u32(40226, 500000)  -- exported Wh (SF 0) -> 500.0 kWh
u32(40228, 180000)  -- exported phase A
u32(40230, 170000)  -- exported phase B
u32(40232, 150000)  -- exported phase C
u32(40234, 100000)  -- imported Wh -> 100.0 kWh
w(40242, 0)      -- energy SF
w(40245, 0xFFFF) -- SunSpec end marker

-- ------------------------------ StorEdge battery floats (SE low word first)
-- (the user QA's 1-based 57716/57732 -> 0-based 57715/57731 here; its
-- decodeFloat32 wants the HIGH word first)
words(57715, helpers.f32(1200.5, false))  -- battery power W (charging)
words(57731, helpers.f32(85.0, false))    -- SOC %

return { map = MAP }
