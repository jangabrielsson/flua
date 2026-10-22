--%%name:SolarEdge Mock Driver
--%%type:com.fibaro.binarySwitch
--%%property:isHidden=true
-- --------------- EOH ---------------
-- End-to-end demo: run the SolarEdge Live QA against the mock, then press
-- the mock's buttons and verify the QA's main-device value follows on its
-- next poll. Run all three together (the user's QA stays untouched):
--
--   flua "dev/SolarEdge Live/main.lua" \
--        "examples/Modbus Server/solaredge_mock.lua" \
--        "examples/Modbus Server/run_solaredge.lua" \
--        -D "var:host='127.0.0.1'" --run-for 60
--
-- Prints PASS/FAIL lines and exits with the failure count. Runs fine on its
-- own too (skips when the two QAs are not present).

local failures = 0

local function findDevice(name)
  local devices = api.get("/devices") or {}
  for _, dev in ipairs(devices) do
    if dev.name == name then return dev end
  end
  return nil
end

local function press(deviceId, elementName)
  api.post("/plugins/callUIEvent", {
    deviceId = deviceId,
    elementName = elementName,
    eventType = "onReleased",
  })
end

local function valueOf(deviceId)
  local dev = api.get("/devices/" .. deviceId)
  return dev and tonumber(dev.properties and dev.properties.value)
end

local function check(cond, label)
  if cond then
    print("PASS: " .. label)
  else
    failures = failures + 1
    print("FAIL: " .. label)
  end
end

-- wait until fn() is truthy, polling every second; returns true/false
local function waitFor(fn, maxTries)
  local tries = 0
  while tries < maxTries do
    if fn() then return true end
    tries = tries + 1
    fibaro.sleep(1000)
  end
  return false
end

function QuickApp:onInit()
  local se = findDevice("SolarEdge Live")
  local mock = findDevice("SolarEdge Mock")
  if not se or not mock then
    print("SKIP: needs 'SolarEdge Live' and 'SolarEdge Mock' QAs in the same run")
    exit(0)
  end
  print("driver: found " .. se.name .. " (id " .. se.id .. ") and " .. mock.name)
  -- wait for the QA's first poll: it reads the mock's initial map
  -- (AC power 2500 W); boot and the socket roundtrip are async
  local ok = waitFor(function() return (valueOf(se.id) or 0) ~= 0 end, 20)
  check(ok, "initial value arrives on the first poll")
  local base = valueOf(se.id) or 0

  -- press Sun +500W and wait for the QA's next poll (default interval 10 s)
  press(mock.id, "btnSunUp")
  local sawUp = waitFor(function() return (valueOf(se.id) or 0) == base + 500 end, 20)
  check(sawUp, "AC power follows 'Sun +500W' (" .. tostring(base) .. " -> " .. tostring(base + 500) .. ")")

  -- press Sun -500W and wait for it to come back down
  press(mock.id, "btnSunDown")
  local sawDown = waitFor(function() return (valueOf(se.id) or 0) == base end, 20)
  check(sawDown, "AC power follows 'Sun -500W' (back to " .. tostring(base) .. ")")

  print(("failures: %d"):format(failures))
  exit(failures)
end
