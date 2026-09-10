-- async.run / async.await / async.wait: async results resume the coroutine
local script_dir = (arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

local function fail(err)
  t.expect(false, "async failed: " .. tostring(err))
  exit(1)
end

async.run(function()
  -- await delivers the async result into the coroutine
  local a = async.await(function(finish)
    setTimeout(function() finish(21) end, 30)
  end)
  t.expect_eq(a, 21, "first async result")

  local b = async.await(function(finish)
    setTimeout(function() finish(a * 2) end, 30)
  end)
  t.expect_eq(b, 42, "second async result, computed from the first")

  -- the pump keeps running while the coroutine waits
  local flag = false
  setTimeout(function() flag = true end, 20)
  async.wait(60)
  t.expect(flag, "other timers fired while the coroutine waited")

  -- multiple values flow through await
  local x, y = async.await(function(finish)
    setTimeout(function() finish(3, 4) end, 20)
  end)
  t.expect_eq(x + y, 7, "multiple values flow through await")

  -- errors reach onError, and the failing run does not disturb this one
  local caught
  async.run(function()
    async.wait(10)
    error("kaboom")
  end, function(err) caught = tostring(err) end)
  async.wait(40)
  t.expect_match(caught, "kaboom", "onError received the coroutine error")

  t.done()
end, fail)
