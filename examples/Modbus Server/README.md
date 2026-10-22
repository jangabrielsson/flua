# Modbus Server — mock a Modbus TCP device from inside a QA

A general Modbus TCP server for flua, plus a ready-made SolarEdge (SunSpec)
mock. Run a user's Modbus QA **unchanged** against it, and change the mocked
values at runtime with buttons on the mock QA.

Files:

- `modbus_server.lua` — the generic server library (register table + FC3
  read / FC6 / FC16 writes over `net.TCPServer`, persistent connections,
  partial-frame buffering per connection).
- `solaredge.lua` — the SunSpec register map (the values) for a SolarEdge
  inverter, keyed at 0-based SunSpec register numbers.
- `sunspec-implementation-technical-note.pdf` — the SolarEdge SunSpec
  logging technical note (v3.3, October 2026, knowledge-center.solaredge.com),
  the source of truth for `solaredge.lua`. Its register tables list
  "Address (base 0)" and "(base 1)" columns; the base-0 column is the
  MODBUS Protocol Address that goes on the wire.
- `solaredge_mock.lua` — the SolarEdge mock QA: starts the server on port
  1502 and adds buttons (Sun +/-, Grid export/import, battery SOC) that
  mutate the map.
- `run_solaredge.lua` — a driver that presses the mock's buttons and verifies
  the client QA's value follows (exit code = failure count).

## Run the SolarEdge Live user QA against the mock

```bash
.venv/bin/flua "dev/SolarEdge Live/main.lua" \
     "examples/Modbus Server/solaredge_mock.lua" \
     "examples/Modbus Server/run_solaredge.lua" \
     -D "var:host='127.0.0.1'" --run-for 45 --speed 60
```

The user QA is not modified — `-D var:host=…` is a directive-level variable
override (the QA defaults to `192.168.1.145`; the mock binds `127.0.0.1`).
Expected output: the QA reads 2500 W on its first poll, the driver presses
*Sun +500W* → 3000 W on the next poll, *Sun -500W* → back to 2500 W, and
`failures: 0`.

With `--ui 8090` you can press the mock's buttons in the viewer
(http://127.0.0.1:8090/) instead of using the driver — the SolarEdge Live
QA's own buttons (Inverter/Meter/Power blocks) also work against the mock.

## Address conventions (the part that usually bites)

Your QA puts a **PDU address** on the wire. The mock translates it to your
map key with `mapKey = base + pduAddress`. Pick `base` to match the QA:

- `base = 40000` — QAs with 1-based register numbers that subtract 40001
  (the SolarEdge Live QA; its "40084" is 0-based SunSpec 40083).
- `base = 40001` — QAs with classic 4xxxx holding-register numbers
  (the default).
- `base = 0` — QAs that send the register number itself
  (the Solar Edge Modbus Demo QA).

For SolarEdge specifically, the technical note is unambiguous about the
SunSpec map: the block base "is set to 40070 (MODBUS PLC address [base 1]),
or 40069 (MODBUS Protocol Address [base 0])" — the base-0 column is the
wire address, so SunSpec sits at 40000+. A QA that subtracts 40001 instead
addresses the **legacy SE protocol** layout (same model, same numbers, low
wire addresses). A live read from the QA author's inverter confirmed real
devices serve AC power at BOTH bases (PDU 40083 and PDU 83) — the
SolarEdge Live QA is fine on real hardware, and the mock's `base = 40000`
serves the SunSpec map at its addresses (equivalent for the inverter
block; the legacy map's meter coverage is unverified).

Unknown addresses reply 0 (a real device answers the whole span); set
`zeroFill = false` to answer illegal-data-address exceptions instead.

### The 125-register read limit

A Modbus read reply carries its data length in one wire byte, so a request
for more than 125 registers cannot be answered in full — real devices send
an exception. The SolarEdge Live QA reads its whole filter as ONE request,
so with several block buttons enabled its span can exceed 125 (it checks
the number of filter *entries*, not the span). On a real inverter those
reads fail and the QA silently disconnects after its `maxResponseTime`; the
mock instead answers with the first 125 registers of the span and logs
`read for N registers capped at 125` — the leading part of the QA's filter
(children, main register, meter) stays live, the tail beyond the wire limit
shows 0. Press one block at a time for a span that fits (the Meter block
fits; adding Power/Import-Export/Inverter on top does not).

## Instrument a new device

Copy `solaredge.lua` + `solaredge_mock.lua` and swap the map:

```lua
local server = require("modbus_server")   -- the generic engine
local helpers = server.helpers

local MAP = {}
local function w(addr, v) MAP[addr] = v % 65536 end
local function words(addr, list)
  for i, v in ipairs(list) do w(addr + i - 1, v) end
end
words(40001, { 1234, 5678 })              -- two 16-bit registers
words(40010, helpers.u32(1000000))        -- one big-endian u32
words(40020, helpers.ascii("Hello"))      -- one ASCII string
words(40030, helpers.f32(230.0))          -- one float32 (high word first)

local mock = server.serve(MAP, { port = 1502, base = 40001 })
```

Mutating `MAP` at runtime changes what clients read on their next poll —
that is all the buttons in `solaredge_mock.lua` do. `onWrite` hooks FC6/FC16
writes, `onRead` hooks reads, `verbose = true` logs every request.

## How it is tested

`tests/test_modbus_mock.py` pins four contracts: the HC3 string extensions
(`string.starts`/`string.ends`), `--%%var` values visible as
`quickAppVariables` during `onInit` (so QAs that build children from
variables work), the mock + buttons round-trip with a stand-in for the
SolarEdge Live QA's wire pattern, and the FC6/FC16 write round-trip
including the 125-register read cap.
