--%%name:qa-one
-- Example QA pair: run with
--   .venv/bin/flua examples/qa1.lua examples/qa2.lua
-- Each QA runs in its own environment and prints its own number.
-- Each QA's _FLUA.config holds that QA's own config (--%%name:qa-one).
local name = _FLUA.config.name
print(_FLUA.config.name .. ": 1")
setTimeout(function()
  print(name .. ": 2")
end, 300)
