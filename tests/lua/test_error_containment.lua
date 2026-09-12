-- errors inside callbacks are contained; the engine keeps running
local script_dir = (_FLUA.arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

setTimeout(function() error("boom") end, 10)

setTimeout(function()
  t.expect(true, "engine survived the callback error")
  t.done()
end, 80)
