-- HC3-compatible JSON for QA code and mobdebug's VSCODE debugger protocol.
--
-- flua keeps the runtime dependencies tiny, so JSON lives in the Python
-- bridge: `_PY.to_json` / `_PY.parse_json` (stdlib json, with the lupa
-- table conversion the engine already uses for messages).
local json = {}

json.encode = function(value) return _PY.to_json(value) end
json.decode = function(text) return _PY.parse_json(text) end

-- HC3 compatibility: mark a table as an array so the encoder renders it as
-- "[...]" — including an empty table as "[]" instead of "{}", which is the
-- one case the 1..n key heuristic cannot decide. Adds the flag to an
-- existing metatable instead of replacing it.
json.util = {}
function json.util.InitArray(e)
  local mt = getmetatable(e) or {}
  mt.__isArray = true
  return setmetatable(e, mt)
end

return json
