--%%name:SkodaMock
-- myskoda_mock.lua — a mock MyŠkoda Public API server (net.HTTPServer)
--
-- Serves the subset of the public API the control QA
-- (myskoda.lua) uses, so the pair runs fully offline:
--
--   flua --api local examples/Skoda/myskoda_mock.lua examples/Skoda/myskoda.lua
--
-- Endpoints (X-API-Key accepted but not verified — any key works):
--   GET  /api/v1/vehicles/{vin}                  the vehicle state
--   POST /api/v1/vehicles/{vin}/charging/start   202, state -> CHARGING
--   POST /api/v1/vehicles/{vin}/charging/stop    202, state -> READY_FOR_CHARGING
--   PUT  /api/v1/vehicles/{vin}/charging/limit   202, sets the target SOC
--   POST /api/v1/vehicles/{vin}/air-conditioning/start  202, climate -> ON
--   POST /api/v1/vehicles/{vin}/air-conditioning/stop   202, climate -> OFF
--
-- Prints every request as "MOCK <METHOD> <path>" (tests pin those lines)
-- and "SKODA_MOCK listening on <port>" once ready.

local state = {
  soc = 71,                        -- battery state of charge, percent
  charging = "READY_FOR_CHARGING", -- the ChargingStatus.state vocabulary
  target = 80,                     -- target SOC, percent
  climate = "OFF",                 -- air-conditioning state
}

local function vehicle()
  return {
    vin = "TMBMOCK123456789",
    status = { overall = "CLOSED_LOCKED" },
    charging = {
      status = {
        state = state.charging,
        battery = { stateOfChargeInPercent = state.soc, remainingCruisingRangeInMeters = 249000 },
      },
      settings = { targetStateOfChargeInPercent = state.target },
    },
    airConditioning = { state = state.climate },
  }
end

local function reply(status, body)
  return { status = status, body = body, headers = { ["Content-Type"] = "application/json" } }
end

local function handle(req)
  print("MOCK", req.method, req.url)
  local method, url = req.method, req.url
  if method == "GET" and url:match("^/api/v1/vehicles/[^/]+$") then
    return reply(200, json.encode(vehicle()))
  end
  local action = url:match("^/api/v1/vehicles/[^/]+/(charging/start)$")
    or url:match("^/api/v1/vehicles/[^/]+/(charging/stop)$")
    or url:match("^/api/v1/vehicles/[^/]+/(charging/limit)$")
    or url:match("^/api/v1/vehicles/[^/]+/(air%-conditioning/start)$")
    or url:match("^/api/v1/vehicles/[^/]+/(air%-conditioning/stop)$")
  if not action then
    return reply(404, json.encode({ error = "not found" }))
  end
  if action == "charging/start" and method == "POST" then
    state.charging = "CHARGING"
  elseif action == "charging/stop" and method == "POST" then
    state.charging = "READY_FOR_CHARGING"
  elseif action == "charging/limit" and method == "PUT" then
    local ok, body = pcall(json.decode, req.body)
    if ok and type(body) == "table" and body.targetStateOfChargeInPercent then
      state.target = body.targetStateOfChargeInPercent
    end
  elseif action == "air-conditioning/start" and method == "POST" then
    state.climate = "ON"
  elseif action == "air-conditioning/stop" and method == "POST" then
    state.climate = "OFF"
  else
    return reply(405, json.encode({ error = "method not allowed" }))
  end
  return reply(202, "")
end

-- the mock serves a FIXED, deliberately unlikely port (the control QA
-- defaults to the same one) — overridable via the `port` variable
local MOCK_PORT = 18290

function QuickApp:onInit()
  local port = tonumber(self:getVariable("port")) or MOCK_PORT
  local ok, srv = pcall(function()
    local server = net.HTTPServer()
    server:listen(port, handle)
    return server
  end)
  if not ok then
    -- the port is taken: an external mock (the two-QA style) or another
    -- service serves it — stand down rather than pretend to serve
    self:warning("cannot bind port " .. port .. " — another mock or service serves it")
    exit(0)
    return
  end
  print("SKODA_MOCK listening on " .. srv.port)
  _FLUA.keepAlive()  -- serve for the whole run
end
