"""HC3-compatible json module: encode/decode and json.util.InitArray."""

import pytest

pytest.importorskip("lupa")

import json

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
assert(json.encode({ arr = json.util.InitArray({}) }) == '{"arr":[]}')
-- unmarked dense tables keep the 1..n heuristic; the encoder is COMPACT
-- like the HC3's (no spaces after commas/colons — string-exact
-- assertions written for plua/the real HC3 compare byte-for-byte)
assert(json.encode({ "a", "b" }) == '["a","b"]')
assert(json.encode({ x = 1 }) == '{"x":1}')
assert(json.encode({ 2, 4, 6 }) == '[2,4,6]')
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


async def test_json_encode_formatted_pretty_prints() -> None:
    # the field-report ask: json.encodeFormatted for fixture dumps; the
    # compact encoder stays the byte-exact default
    engine = LuaEngine(api_mode="local")
    await engine.start()
    try:
        result = engine.execute(
            'return json.encode({a=1,b={2,3}}), json.encodeFormatted({a=1,b={2,3}})'
        )
        compact, pretty = result
        assert json.loads(compact) == {"a": 1, "b": [2, 3]}  # unchanged shape
        assert ", " not in compact  # the compact separator stays byte-tight
        assert "\n" in pretty and '"a": 1' in pretty and '    ' in pretty
        assert json.loads(pretty) == {"a": 1, "b": [2, 3]}
    finally:
        await engine.stop()
