-- setInterval chains setTimeout; clearInterval stops it
local script_dir = (_FLUA.arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

local ticks = 0
local iv
iv = setInterval(function()
  ticks = ticks + 1
  if ticks >= 3 then clearInterval(iv) end
end, 20)

setTimeout(function()
  t.expect_eq(ticks, 3, "interval ticked exactly 3 times")
  -- a moment later it must still be 3 — the interval is really cleared
  setTimeout(function()
    t.expect_eq(ticks, 3, "interval stayed cleared")
    t.done()
  end, 200)
end, 250)
