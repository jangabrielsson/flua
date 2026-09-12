--%%name:qa-two
-- Example QA pair: run with
--   .venv/bin/flua examples/qa1.lua examples/qa2.lua
-- Each QA runs in its own environment and prints its own number.
-- Each QA's _FLUA.config holds that QA's own config (--%%name:qa-two).
local name = _FLUA.config.name
print(_FLUA.config.name .. ": 100")
setTimeout(function()
  print(name .. ": 200")
end, 300)
