-- coroutine + timer cooperation: async results resume the coroutine
local script_dir = (arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

-- suspends the running coroutine; the timer resumes it later with 42.
-- returns whatever the resumer passed in — i.e. the async result.
local function sleeper(ms)
  local co = coroutine.running()
  setTimeout(function()
    local ok, err = coroutine.resume(co, 42)
    if not ok then
      print("FAIL: " .. tostring(err))
      exit(1)
    end
  end, ms)
  return coroutine.yield()
end

-- drive the whole test body as a coroutine, so timers can resume it.
-- (a plain coroutine.wrap(sleeper)(ms) returns the first yield value, which
-- is nil — the 42 arrives asynchronously and wrap cannot surface it)
local function run(fn)
  local co = coroutine.create(fn)
  local ok, err = coroutine.resume(co)
  if not ok then
    print("FAIL: " .. tostring(err))
    exit(1)
  end
end

run(function()
  local a = sleeper(10)
  t.expect_eq(a, 42, "first async result resumes the coroutine")

  local b = sleeper(10)
  t.expect_eq(a + b, 84, "second async result continues where it yielded")

  t.done()
end)
