-- helpers.lua — minimal test harness for tests/lua/ CLI tests.
--
-- Usage from a test script:
--
--   local script_dir = (_FLUA.arg[0] or "."):match("^(.*)[/\\]") or "."
--   local t = dofile(script_dir .. "/helpers.lua")
--   ...
--   t.done()
--
-- A test passes when it calls t.done() with zero failures (exit 0); any
-- failure makes t.done() _FLUA.exit(1). The Python runner (tests/test_lua.py)
-- asserts on the exit code and the "all passed" marker.

local M = {}
M.checks = 0
M.failures = 0

function M.expect(cond, msg)
  M.checks = M.checks + 1
  if not cond then
    M.failures = M.failures + 1
    print("FAIL: " .. tostring(msg or "expect failed"))
  end
end

function M.expect_eq(actual, expected, msg)
  M.checks = M.checks + 1
  if actual ~= expected then
    M.failures = M.failures + 1
    print("FAIL: " .. tostring(msg or "expect_eq"))
    print("  expected: " .. tostring(expected))
    print("  actual:   " .. tostring(actual))
  end
end

function M.expect_match(text, pattern, msg)
  M.checks = M.checks + 1
  if not tostring(text):match(pattern) then
    M.failures = M.failures + 1
    print("FAIL: " .. tostring(msg or "expect_match"))
    print("  text:    " .. tostring(text))
    print("  pattern: " .. tostring(pattern))
  end
end

function M.done()
  if M.failures > 0 then
    print(string.format("%d check(s), %d failure(s)", M.checks, M.failures))
    _FLUA.exit(1)
    return
  end
  print(string.format("%d check(s), all passed", M.checks))
  _FLUA.exit(0)
end

return M
