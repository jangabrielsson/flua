--%%name:OnInitQA
-- Every QA gets a QuickApp instance constructed after its code loads;
-- :onInit is called as part of that construction (HC3 startup semantics).
-- The id is always assigned by the engine.
local script_dir = (_FLUA.arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

local inited = false
function QuickApp:onInit()
  inited = true
  t.expect_eq(self.id, _FLUA.qaId, "onInit sees the engine-assigned id")
end

setTimeout(function()
  t.expect(inited, "onInit was called during bootstrap")
  t.expect_eq(_FLUA.qaId, 5000, "engine-assigned id starts at 5000")
  local qa = _FLUA.qa(_FLUA.qaId)
  t.expect(qa ~= nil, "instance registered")
  t.expect_eq(qa.name, "OnInitQA", "instance has the config name")
  t.expect_eq(qa.id, _FLUA.qaId, "instance has the engine-assigned id")
  t.done()
end, 100)
