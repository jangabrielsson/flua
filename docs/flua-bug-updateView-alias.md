# flua bug: `updateView` aliases one object into `view` and `properties.uiView` → lupa "lost reference"

- **flua**: 0.1.86 (bug present)
- **lupa**: 2.6
- **Where**: simulator only (offline mode). The real HC3 never converts Python→Lua
  tables this way, so this cannot happen on hardware.
- **Severity**: a whole `QuickApp` callback dies at startup. In HassQA it kills
  `getChildrenUidMap()` inside `authenticated`, so `populatePopup` never runs and
  child popups stay empty. Websocket flow itself is unaffected (that was the
  0.1.86 handshake fix — unrelated).

## Symptom

```
Error in bootstrap:	lost reference
    .../flua/lua/init.lua:1003
```

or, mid-run:

```
Callback error: lost reference
```

## Minimal repro (standalone QA)

```lua
--%%name:upv-repro
--%%type:com.fibaro.binarySwitch
function QuickApp:onInit()
  local child = api.post("/plugins/createChildDevice", {
    parentId = self.id, name = "child", type = "com.fibaro.binarySwitch",
    initialProperties = {uiView = {
      {label='row', components={
        {select='presetSelector', name='presetSelector', text='Preset',
         options={{text='a'},{text='b'}}, values={}, onToggled='cb'}
      }}
    }}, initialInterfaces = {},
  })
  api.post("/plugins/updateView", {
    deviceId = child.id, componentName = "presetSelector",
    propertyName = "options", newValue = {{text='x'},{text='y'}},
  })
  api.get("/devices?parentId=" .. self.id)   -- "Error in bootstrap: lost reference"
end
```

Run: `flua --api local --instant upv-repro.lua`

The trigger is: a child device whose `uiView` contains a component with
`name == componentName`, followed by `updateView` on that component, followed
by any `GET /devices` that returns that child.

## Root cause

Every step below was verified in isolation:

1. **`updateView` stores the same object twice.**
   `QuickAppBase:updateView` (`flua/lua/quickapp.lua:149`) posts
   `/plugins/updateView` with `newValue`. The route
   `plugin_update_view` (`flua/api/routes/plugins.py`) writes
   `new_value = req.body.get("newValue")` into **two** places of the device
   state:
   - `view[component_name][property_name]` (`plugins.py:270`), and
   - the matching component of the stored `properties.uiView`
     (`plugins.py:274-279`):

   ```python
   ui_view = (dev.get("properties") or {}).get("uiView")
   if isinstance(ui_view, list):
       for row in ui_view:
           for comp in row.get("components") or []:
               if comp.get("name") == component_name:
                   comp[property_name] = new_value   # same object again
                   break
   ```

   The **same Python list object** is now reachable from two paths in the
   device state:
   `properties.uiView[1].components[0].options` and
   `view.presetSelector.options`.

2. **`public()` preserves the aliasing.**
   `GET /devices?parentId=…` serves via `public()` = `copy.deepcopy`
   (`flua/api/state.py:77-79`). `deepcopy`'s memo keeps shared objects
   shared, so the response payload still contains one list reachable via two
   paths. Verified: `view.presetSelector.options is properties.uiView[1]
   .components[0].options` is `True` in the served payload.

3. **lupa's `table_from(recursive=True)` wraps a stale stack slot.**
   `bindings.api_call` (`flua/bindings.py:235`) converts the response with
   `lua.table_from(data, recursive=True)`. lupa 2.6's `py_to_lua_table`
   (`lua54.pyx:1718-1724`) keeps an identity-dedup map
   `mapped_tables[id(obj)] = lua_table_ref`, where `lua_table_ref` is the
   **stack index** of the table being filled at first encounter. On the
   second encounter it does `new_lua_table(runtime, L, idx)` →
   `lua_pushvalue(L, idx)`.

   The first occurrence of the shared list is *deep* in the tree
   (`properties` → `uiView[1]` → `components[0]` → `options`), the second is
   *shallow* (`view` → `presetSelector` → `options`). `properties` precedes
   `view` in the device dict (skeleton key order), so by the time the shallow
   copy is converted the cached stack index lies **above the current stack
   top**. `lua_pushvalue(idx)` then pushes **nil** → `luaL_ref` →
   `LUA_REFNIL` → `push_lua_object` sees nil → `LuaError("lost reference")`
   (`lua54.pyx:904/908`).

   Same-depth aliasing does *not* fail (the stale slot still holds the
   original table by luck), which is why naive aliasing tests pass and this
   looked flaky.

Minimal lupa-only repro (no flua needed):

```python
from lupa import LuaRuntime
shared = [{"text": "none"}, {"text": "away"}]
payload = {
    "properties": {"uiView": [{"components": [{"options": shared}]}]},  # deep
    "view": {"presetSelector": {"options": shared}},                    # shallow
}
lua = LuaRuntime(unpack_returned_tuples=True, encoding="UTF-8")
lua.table_from(payload, recursive=True)   # LuaError: lost reference
# control: same depth both times -> OK
lua.table_from({"x": {"options": shared}, "y": {"options": shared}}, recursive=True)
```

## Why the 0.1.86 sanitization doesn't catch it

The `_plain_key`/`_plain_value` sanitization added in 0.1.86
(`flua/bindings.py`) removes **lupa proxy objects** from bridge data. This
data is 100% plain Python — the problem is **object identity** (one object
reachable twice), not object type. The sanitizer can't see it.

## Suggested fix (flua-side)

Two independent layers, both cheap:

1. **Root fix — don't share the object in `plugin_update_view`.**
   `view` and `properties.uiView` are two parallel representations; patching
   both with the same mutable object couples them. Store a copy in the
   second write, e.g. `comp[property_name] = copy.deepcopy(new_value)`, or
   copy when writing to `view` instead. (Also worth a scan for other routes
   that write one `req.body` value into two state locations.)

2. **Bridge guard — guarantee tree-shaped data before `table_from`.**
   In `bindings.api_call` (and the other `table_from` sites), round-trip the
   payload before conversion:
   `data = json.loads(json.dumps(data))` — the data is already
   JSON-shaped, so this is safe and O(n). It turns aliased structures into
   duplicated ones, making lupa's dedup path unreachable for *any* aliasing
   source, now and in the future.

Fixing lupa itself (registry refs instead of stack indices in
`py_to_lua_table`) would also work, but that's a third-party change and
arguably lupa's behavior for tree-shaped input is fine — flua should not be
feeding it aliased structures.

## Evidence trail

- Instrumented sim state shows the shared object is already in the store
  (not introduced by `deepcopy`):
  `STORE-DUP device=900028 paths=[('.properties.uiView[1].components[0].options', 2), …]`
- Aliased paths in the failing response payload:
  `[0].properties.uiView[1].components[0].options` ↔
  `[0].view.presetSelector.options` (plus `options[0..6]`)
- The captured failing payload raises in a **fresh** `LuaRuntime`; the same
  payload after `json.loads(json.dumps(...))` converts cleanly.
- Python-level chain replay (create child → updateView → public → table_from)
  reproduces: alias in store `True` → alias after `public()` `True` →
  `table_from` raises.
- End-to-end QA repro above: `Error in bootstrap: lost reference` with
  pristine flua 0.1.86.
