--%%name:SkodaMock
--%%type:com.fibaro.genericDevice
--%%u:{label='battery',text='Battery'}
--%%u:{label='chargeState',text='Charging state'}
--%%u:{label='climate',text='A/C Status'}
--%%u:{label='target',text='Target charge'}
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
  chargingSince = nil,             -- os.time() when CHARGING started
}

-- the battery charges while CHARGING until the target: chargeRate percent
-- per (virtual) hour — set the `chargeRate` variable to speed the
-- simulation up (the mock's os.time() is flua's virtual clock, so the
-- run's --%%speed/--speed accelerates it too)
local chargeRate = 10

local function advance()
  if state.charging == "CHARGING" and state.soc < state.target and state.chargingSince then
    local elapsed = os.time() - state.chargingSince
    state.soc = math.min(state.target, state.soc + (chargeRate / 3600) * elapsed)
    if state.soc >= state.target then
      state.soc = state.target
      state.charging = "READY_FOR_CHARGING"
      state.chargingSince = nil
    end
  end
end

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

-- the mock's own labels mirror the served state (the QA instance is
-- captured in onInit — handlers run in the QA context)
local qa
local function updateMockUI()
  if qa then
    qa:updateView("battery", "text", "Battery: " .. string.format("%.1f", state.soc) .. " %")
    qa:updateView("chargeState", "text", "Charging state: " .. state.charging)
    qa:updateView("climate", "text", "A/C Status: " .. state.climate)
    qa:updateView("target", "text", "Target charge: " .. tostring(state.target) .. " %")
  end
end

-- the real API rate-limits 20 requests/hour per VIN (see the bundled
-- developer docs); the mock emulates it, headers included, so the pair
-- teaches the real constraint offline
local rate = { count = 0, window = os.time() }

local function reply(status, body, extra)
  extra = extra or {}
  extra["Content-Type"] = "application/json"
  return { status = status, body = body, headers = extra }
end

local function rateHeaders()
  local now = os.time()
  if now - rate.window >= 3600 then
    rate.window = now
    rate.count = 0
  end
  return {
    ["RateLimit-Limit"] = "20",
    ["RateLimit-Remaining"] = tostring(20 - rate.count),
    ["RateLimit-Reset"] = tostring(3600 - (now - rate.window)),
  }
end

local function handle(req)
  print("MOCK", req.method, req.url)
  advance()
  rate.count = rate.count + 1
  if rate.count > 20 then
    local extra = rateHeaders()
    extra["Retry-After"] = tostring(extra["RateLimit-Reset"])
    return reply(429, json.encode({ error = "rate limited" }), extra)
  end
  local method, url = req.method, req.url
  if method == "GET" and url:match("^/api/v1/vehicles/[^/]+$") then
    return reply(200, json.encode(vehicle()), rateHeaders())
  end
  local action = url:match("^/api/v1/vehicles/[^/]+/(charging/start)$")
    or url:match("^/api/v1/vehicles/[^/]+/(charging/stop)$")
    or url:match("^/api/v1/vehicles/[^/]+/(charging/limit)$")
    or url:match("^/api/v1/vehicles/[^/]+/(air%-conditioning/start)$")
    or url:match("^/api/v1/vehicles/[^/]+/(air%-conditioning/stop)$")
  if not action then
    return reply(404, json.encode({ error = "not found" }), rateHeaders())
  end
  if action == "charging/start" and method == "POST" then
    state.charging = "CHARGING"
    state.chargingSince = os.time()
  elseif action == "charging/stop" and method == "POST" then
    state.charging = "READY_FOR_CHARGING"
    state.chargingSince = nil
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
    return reply(405, json.encode({ error = "method not allowed" }), rateHeaders())
  end
  updateMockUI()
  return reply(202, "", rateHeaders())
end

-- the mock serves a FIXED, deliberately unlikely port (the control QA
-- defaults to the same one) — overridable via the `port` variable
local MOCK_PORT = 18290

function QuickApp:onInit()
  qa = self
  chargeRate = tonumber(self:getVariable("chargeRate")) or chargeRate
  updateMockUI()
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
