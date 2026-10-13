-- flua-test — the verify-loop assertions library.
--
-- Two entry paths, one file:
--
--   local Test = require("flua-test")   -- provided by flua itself; no files
--   local t = Test.new()                -- on disk, nothing travels in the .fqa
--   t:expect(cond, "msg")               -- prints PASS:/FAIL:, counts failures
--   t:assert_eq(got, want, "msg")       -- deep compare (tables included)
--   t:assert_json(text, "msg")          -- json.decode succeeds
--   t:finish()                          -- summary + exit(failures>0 and 1 or 0)
--
-- For asserts that may TRAVEL to a real HC3, declare the library as a QA
-- file — it ships in the .fqa like any --%%file, and on the HC3 every
-- assertion becomes a no-op (the module detects the HC3 by the absence of
-- flua's _FLUA global: no printing, no counting, finish() returns 0):
--
--   --%%file:$flua-test.lua,flua_test   -- loads before main, on flua and HC3
--   local Test = require("flua-test")   -- works on the HC3 too: the file
--                                       -- registered itself in package.preload
--
-- The shipped file also sets the global fluaTest (the classic HC3
-- shared-file idiom) — use fluaTest:expect(...) if you prefer no require.
-- In flua, the shipped copy is the same full-featured library either way;
-- the no-op path only exists where _FLUA does not (a real HC3).
--
-- Output is deliberately lean: PASS:/FAIL: lines via the QA's print (with
-- the log tag), a "failures: N" summary from finish(). The exit code is
-- the verdict — agents read that, not the text.

local json_decode = json and json.decode or nil
local isFlua = type(_FLUA) == "table"

local Test = {}
Test.__index = Test

local function deep_eq(a, b)
  if a == b then
    return true
  end
  local ta, tb = type(a), type(b)
  if ta ~= tb then
    return false
  end
  if ta ~= "table" then
    return false
  end
  local seen = {}
  for k, v in pairs(a) do
    if not deep_eq(v, b[k]) then
      return false
    end
    seen[k] = true
  end
  for k in pairs(b) do
    if not seen[k] then
      return false
    end
  end
  return true
end

function Test.new()
  local self = setmetatable({}, Test)
  self.passes = 0
  self.failures = 0
  return self
end

function Test:expect(cond, msg)
  if not isFlua then
    return cond and true or false  -- HC3: inert (arguments still evaluate)
  end
  msg = tostring(msg or "")
  if cond then
    self.passes = self.passes + 1
    print("PASS: " .. msg)
  else
    self.failures = self.failures + 1
    print("FAIL: " .. msg)
  end
  return cond and true or false
end

function Test:assert_eq(got, want, msg)
  if not isFlua then
    return true
  end
  return self:expect(deep_eq(got, want), (msg and msg .. " — " or "") .. "expected "
    .. tostring(want) .. ", got " .. tostring(got))
end

function Test:assert_json(text, msg)
  if not isFlua then
    return true
  end
  if not json_decode then
    return self:expect(false, (msg and msg .. " — " or "") .. "json module unavailable")
  end
  local ok, decoded = pcall(json_decode, text)
  if not ok then
    return self:expect(false, (msg and msg .. " — " or "") .. "invalid JSON: " .. tostring(decoded))
  end
  return self:expect(true, msg or "valid JSON")
end

function Test:results()
  return { passes = self.passes, failures = self.failures }
end

function Test:finish()
  if not isFlua then
    return 0  -- HC3: no summary, no exit
  end
  print("failures: " .. tostring(self.failures))
  if type(exit) == "function" then
    exit(self.failures > 0 and 1 or 0)
  end
  return self.failures
end

-- The shipped-file path: register the module so require("flua-test") works
-- in files loaded after this one (main loads last) — on the HC3 this is
-- what makes the require spelling work at all. In flua the runtime already
-- provides the module; re-registering is harmless and idempotent.
if type(package) == "table" then
  package.preload["flua-test"] = function()
    return Test
  end
end
fluaTest = Test  -- the HC3 shared-file idiom (a global in the QA's state)

return Test
