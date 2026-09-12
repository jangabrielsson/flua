-- The QA runtime libs (class/quickapp/fibaro) load before this script, so
-- QuickApp/QuickAppBase/fibaro/plugin/hub are available here.
local script_dir = (_FLUA.arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

t.expect(type(QuickApp) == "table", "QuickApp class loaded")
t.expect(type(QuickAppBase) == "table", "QuickAppBase class loaded")
t.expect(type(fibaro) == "table", "fibaro loaded")
t.expect(type(__fibaro_add_debug_message) == "function", "HC3 global __fibaro_add_debug_message present")

local dev = {
  name = "TestQA",
  id = 88,
  type = "com.fibaro.binarySwitch",
  properties = { value = true },
}
local qa = QuickApp(dev)
t.expect_eq(qa.name, "TestQA", "qa name")
t.expect_eq(qa.id, 88, "qa id")
t.expect_eq(qa.type, "com.fibaro.binarySwitch", "qa type")
t.expect_eq(qa.properties.value, true, "properties copied")

-- the engine constructs this QA's own instance AFTER the chunk runs
setTimeout(function()
  t.expect_eq(_FLUA.qaId, 5000, "engine-assigned id starts at 5000")
  local auto = _FLUA.qa(_FLUA.qaId)
  t.expect(auto ~= nil, "auto instance created")
  t.expect_eq(auto.name, "test_quickapp", "auto instance named after the file")
  t.done()
end, 0)
