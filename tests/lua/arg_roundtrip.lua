-- arg table: arg[0] = the QA's own script path.
-- Run explicitly by tests/test_lua.py::test_arg_table_roundtrip.
local script_dir = (arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

t.expect_match(arg[0], "arg_roundtrip%.lua$", "arg[0] is the script path")
t.expect_eq(arg[1], nil, "no extra CLI arguments in QA mode")
t.expect(type(config) == "table", "QA config table exists")

t.done()
