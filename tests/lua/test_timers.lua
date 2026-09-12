-- cooperative timers: one-shot, delay ordering, clearing
local script_dir = (_FLUA.arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

local order = {}
setTimeout(function() order[#order + 1] = "slow" end, 60)
setTimeout(function() order[#order + 1] = "fast" end, 10)

local late = setTimeout(function() order[#order + 1] = "cancelled" end, 40)
setTimeout(function() clearTimeout(late) end, 5)

setTimeout(function()
  t.expect_eq(table.concat(order, ","), "fast,slow", "timers fire in delay order")
  t.expect_eq(order[3], nil, "cancelled timer never fired")
  t.done()
end, 150)
