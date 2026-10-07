--%%name:self_test
-- selfTest.lua — a QA as its own test suite
--
-- Run it offline:  flua --api local examples/selfTest.lua
-- The QA asserts its own behavior against the simulated HC3, then exits
-- with the number of failures — the shell (or a coding agent) checks the
-- exit code and the PASS/FAIL lines. A runtime error also exits non-zero,
-- so every code path is covered: exit 0 = the QA logic holds.
--
-- Pattern: assert inside the QA, print PASS/FAIL, and exit(failures) at
-- the end. See also the quickapp-test agent skill (flua --tool setup).

local failures = 0

local function assertTrue(cond, msg)
  if cond then
    print("PASS: " .. msg)
  else
    failures = failures + 1
    print("FAIL: " .. msg)
  end
end

local function assertEq(actual, expected, msg)
  if tostring(actual) == tostring(expected) then
    print("PASS: " .. msg .. " (" .. tostring(actual) .. ")")
  else
    failures = failures + 1
    print("FAIL: " .. msg .. " — expected " .. tostring(expected) .. ", got " .. tostring(actual))
  end
end

function QuickApp:onInit()
  -- the QA under test — its own logic, checked against the simulated HC3
  local device = api.get("/devices/" .. self.id)
  assertEq(device.id, self.id, "the device is visible in the sim")
  assertTrue(self.id >= 5000, "emulated QA ids start at 5000")

  self:updateProperty("value", 50)
  assertEq(self.properties.value, 50, "updateProperty round trip")

  print("failures:", failures)
  exit(failures > 0 and 1 or 0)
end
