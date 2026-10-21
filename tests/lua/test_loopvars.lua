-- HC3 QAs (Lua 5.3) use for-loop variables as mutable temps. flua pins
-- lupa 2.6 (the last Lua 5.4-bundling release) so this stays legal —
-- Lua 5.5 made loop variables const, which broke real QA code.
local script_dir = (_FLUA.arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

local sum = 0
for _, v in ipairs({1, 2, 3}) do
  v = v * 2  -- reassigning the loop variable: legal on the HC3
  sum = sum + v
end
t.expect(sum == 12, "generic-for loop variable is a mutable temp")

local n = 0
for i = 1, 3 do
  i = i + 10
  n = n + i
end
t.expect(n == 36, "numeric-for loop variable is a mutable temp")

t.done()
