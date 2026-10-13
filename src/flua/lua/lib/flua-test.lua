-- flua-test — the verify-loop assertions library.
--
--   local Test = require("flua-test")
--   local t = Test.new()          -- fresh counters
--   t:expect(cond, "msg")         -- prints PASS:/FAIL:, counts failures
--   t:assert_eq(got, want, "msg") -- deep compare (tables included)
--   t:assert_json(text, "msg")    -- json.decode succeeds
--   t:finish()                    -- summary + exit code (failures>0 -> 1)
--
-- flua provides this module through package.preload, so require() works
-- with no files on disk — and, being require'd rather than --%%file'd, it
-- never travels in a packaged .fqa. The library is plain Lua (no flua-only
-- APIs, exit() guarded), so --%%file:$flua-test.lua,test makes the same
-- assertions available on a real HC3 if a QA wants to self-check there.
--
-- Output is deliberately lean: PASS:/FAIL: lines via the plain print (no
-- date/tag decoration), a "failures: N" summary from finish(). The exit
-- code is the verdict — agents read that, not the text.

local json_decode = json and json.decode or nil

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
  return self:expect(deep_eq(got, want), (msg and msg .. " — " or "") .. "expected "
    .. tostring(want) .. ", got " .. tostring(got))
end

function Test:assert_json(text, msg)
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
  print("failures: " .. tostring(self.failures))
  if type(exit) == "function" then
    exit(self.failures > 0 and 1 or 0)
  end
  return self.failures
end

return Test
