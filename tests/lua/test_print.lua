-- print() and _PY basics, checked from Lua.
local script_dir = (_FLUA.arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

t.expect(type(_PY.version()) == "string", "_PY.version() returns a string")
t.expect(type(_PY.now()) == "number", "_PY.now() returns a number")
t.expect(type(setTimeout) == "function", "setTimeout global exists")
t.expect(type(setInterval) == "function", "setInterval global exists")
t.expect(type(_FLUA.exit) == "function", "_FLUA.exit exists")
t.expect(type(exit) == "function", "exit global exists (terminates the QA)")

-- print() round-trip: routed through the message queue to stdout
print("PRINT_MARKER", 42)

t.done()
