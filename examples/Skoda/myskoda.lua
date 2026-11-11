--%%name:Skoda
--%%type:com.fibaro.binarySwitch
--%%interface:battery
-- myskoda.lua — a Skoda car control QA against the MyŠkoda Public API.
--
-- Controls charging and air conditioning through the public REST API
-- (X-API-Key auth; see the bundled OpenAPI spec and the HTML docs in
-- examples/Skoda/). Runs fully offline against the bundled mock:
--
--   flua --api local examples/Skoda/myskoda_mock.lua examples/Skoda/myskoda.lua
--
-- Against the real API, set the QuickApp variables (or the environment):
--   url    the API base url (default: the mock on 127.0.0.1:8190)
--   vin    your vehicle's VIN
--   key    the X-API-Key from the MyŠkoda app
--   once   "true" = refresh once, print, exit (tests); unset = poll every minute
--
-- The QA maps the car onto the declared device properties (`value` =
-- charging on/off, `batteryLevel` from the battery interface) plus
-- QuickApp variables (state, climate, target) and the UI labels — the
-- property set is fixed by the type; the real HC3 silently ignores
-- updates to properties it does not declare.
--   actions: turnOn/turnOff (start/stop charging), setChargingLimit,
--            startAC, stopAC, refresh

--%%u:{label='battery',text='Battery'}
--%%u:{label='state',text='State'}
--%%u:{label='climate',text='Climate'}
--%%u:{label='target',text='Target'}
--%%u:{button='startCharge',text='Start charging',onReleased='startCharging'}
--%%u:{button='stopCharge',text='Stop charging',onReleased='stopCharging'}
--%%u:{button='startAC',text='Start AC',onReleased='startAC'}
--%%u:{button='stopAC',text='Stop AC',onReleased='stopAC'}
--%%u:{slider='chargeLimit',text='Charge limit',min=50,max=100,onChanged='setChargingLimit'}

-- getVariable returns "" for unset variables (flua), and "" is truthy
-- in Lua — so fallbacks need an explicit check, not `or`.
local function first(v, fallback)
  if v == nil or v == "" then return fallback end
  return v
end

-- the mock serves a FIXED port (see myskoda_mock.lua); the control QA
-- defaults straight to it, so no port discovery is needed
local MOCK_PORT = 18290

function QuickApp:onInit()
  self.url = first(self:getVariable("url"), nil)
  if not self.url and _FLUA then
    -- no API configured, running under flua: point at the mock's fixed
    -- port and load the bundled mock QA (one file is the whole pair for
    -- pip users). If a mock already serves the port, the loaded one
    -- stands down quietly. On a real HC3 this is skipped — _FLUA is
    -- flua's extension and the real url is configured instead.
    self.url = "http://127.0.0.1:" .. MOCK_PORT
    print("using the MySkoda mock on " .. MOCK_PORT)
    pcall(_FLUA.loadQAfromFile, _PY.examples_dir .. "/Skoda/myskoda_mock.lua", {})
  elseif not self.url then
    self:warning("no API url configured")
  end
  -- the defaults are the mock's: against the real API, set the
  -- QuickApp variables (vin, key — the X-API-Key from the MySkoda app)
  self.vin = first(self:getVariable("vin"), "TMBMOCK123456789")
  self.key = first(self:getVariable("key"), "test-key")
  self:refresh()
  if self:getVariable("once") ~= "true" then
    setInterval(function() self:refresh() end, 60 * 1000)
  end
end

function QuickApp:request(method, path, body, done)
  local http = net.HTTPClient()
  http:request(self.url .. path, {
    options = {
      method = method,
      headers = { ["X-API-Key"] = self.key },
      data = body and json.encode(body) or nil,
    },
    success = function(resp)
      if resp.status >= 200 and resp.status < 300 then
        if done then done(resp) end
      else
        self:warning(method .. " " .. path .. " -> " .. tostring(resp.status))
      end
    end,
    error = function(err)
      self:error(method .. " " .. path .. ": " .. tostring(err))
    end,
  })
end

function QuickApp:refresh()
  local qa = self
  self:request("GET", "/api/v1/vehicles/" .. self.vin, nil, function(resp)
    local ok, data = pcall(json.decode, resp.data)
    if not ok or type(data) ~= "table" then
      qa:warning("refresh: bad JSON from the API")
      return
    end
    local charging = data.charging or {}
    local status = charging.status or {}
    local battery = status.battery or {}
    local settings = charging.settings or {}
    local ac = data.airConditioning or {}
    -- the device property set is fixed by the type: the declared `value`
    -- mirrors charging, the dynamic state lives in QuickApp variables,
    -- and the UI labels show it (the real HC3 ignores updates to
    -- properties the type does not declare)
    qa:updateProperty("value", status.state == "CHARGING")
    qa:updateProperty("batteryLevel", battery.stateOfChargeInPercent)
    qa:setVariable("state", tostring(status.state or ""))
    qa:setVariable("climate", tostring(ac.state or ""))
    qa:setVariable("target", tostring(settings.targetStateOfChargeInPercent or ""))
    qa:updateView("battery", "text", tostring(battery.stateOfChargeInPercent or "?") .. " %")
    qa:updateView("state", "text", tostring(status.state or "?"))
    qa:updateView("climate", "text", tostring(ac.state or "?"))
    qa:updateView("target", "text", tostring(settings.targetStateOfChargeInPercent or "?") .. " %")
    print("SKODA", battery.stateOfChargeInPercent or "?", status.state or "?")
    if qa:getVariable("once") == "true" then exit(0) end
  end)
end

function QuickApp:startCharging(event)
  self:request("POST", "/api/v1/vehicles/" .. self.vin .. "/charging/start", nil, function()
    self:refresh()
  end)
end

function QuickApp:stopCharging(event)
  self:request("POST", "/api/v1/vehicles/" .. self.vin .. "/charging/stop", nil, function()
    self:refresh()
  end)
end

function QuickApp:setChargingLimit(arg)
  local value = tonumber(type(arg) == "table" and (arg.values and arg.values[1] or arg) or arg)
  if not value then return end
  self:request("PUT", "/api/v1/vehicles/" .. self.vin .. "/charging/limit",
    { targetStateOfChargeInPercent = value }, function()
    self:refresh()
  end)
end

function QuickApp:startAC(event)
  self:request("POST", "/api/v1/vehicles/" .. self.vin .. "/air-conditioning/start", nil, function()
    self:refresh()
  end)
end

function QuickApp:stopAC(event)
  self:request("POST", "/api/v1/vehicles/" .. self.vin .. "/air-conditioning/stop", nil, function()
    self:refresh()
  end)
end

function QuickApp:turnOn() self:startCharging() end
function QuickApp:turnOff() self:stopCharging() end
