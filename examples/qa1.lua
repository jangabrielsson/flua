--%%name:qa-one
-- Example QA pair: run with
--   .venv/bin/flua examples/qa1.lua examples/qa2.lua
-- Each QA runs in its own environment and prints its own number.
-- The QA's config is merged into _FLUA.config at load, so the name is
-- visible engine-wide; capture it for stable per-QA use in callbacks.
local name = _FLUA.config.name
print(_FLUA.config.name .. ": 1")
setTimeout(function()
  print(name .. ": 2")
end, 300)
