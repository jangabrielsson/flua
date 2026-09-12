"""HC3-compatible json module: encode/decode and json.util.InitArray."""

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402


@pytest.mark.asyncio
async def test_json_encode_decode_and_init_array() -> None:
    engine = LuaEngine()
    await engine.start()
    try:
        engine.execute(
            """
-- the HC3 json global is available without require()
assert(require("json") == json)
-- plain empty table encodes as an object; InitArray-marked as an array
assert(json.encode({}) == '{}')
assert(json.encode(json.util.InitArray({})) == '[]')
-- InitArray returns its argument (HC3 signature)
local arr = {}
assert(json.util.InitArray(arr) == arr)
-- an existing metatable is preserved: the flag is added, not replaced
local withMt = setmetatable({}, { __count = 7 })
json.util.InitArray(withMt)
assert(getmetatable(withMt).__isArray == true)
assert(getmetatable(withMt).__count == 7)
assert(json.encode(withMt) == '[]')
-- marking applies to nested values too
assert(json.encode({ arr = json.util.InitArray({}) }) == '{"arr": []}')
-- unmarked dense tables keep the 1..n heuristic
assert(json.encode({ "a", "b" }) == '["a", "b"]')
assert(json.encode({ x = 1 }) == '{"x": 1}')
-- the marker wins over the heuristic in ambiguous cases
local mixed = json.util.InitArray({ [2] = "b" })
assert(json.encode(mixed) == '["b"]')
-- decode roundtrip
local d = json.decode('{"a": [1, 2], "b": 3}')
assert(d.b == 3)
assert(d.a[1] == 1 and d.a[2] == 2)
assert(json.decode("[]") ~= nil)
assert(json.decode("{}") ~= nil)
"""
        )
    finally:
        await engine.stop()
