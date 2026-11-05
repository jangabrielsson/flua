# Note: HC3 classic UI does not re-render slider `value` on updateView

Status: HC3 bug, reported to Fibaro (2026-11-05). flua is intentionally
unaffected — the sim models the API state, not the browser render.

## Symptom (real HC3, live-verified)

On an HC3 running the **classic** web UI (the legacy `viewLayout`/`$jason`
view), a QA that updates a slider's value —

```lua
self:updateView("slider_ID_0", "value", tostring(v))
```

— does not move the slider's visible value, while label and button updates
in the same loop DO re-render:

```lua
self:updateView("label_ID_2", "text", tostring(v))  -- updates visibly
self:updateView("button_ID_1_1", "text", tostring(v))  -- updates visibly
```

Details from the repro:

- macOS, Safari and Chrome — same result.
- The **new mobile view** renders the slider updates correctly.
- A browser **reload** shows the new value — so the HC3's internal state
  is updated; only the classic view's live render of the slider is stale.

## Ground truth (what flua does)

flua has no renderer — its sim models the API-state truth, which is
exactly the "after reload" value the real HC3 stores:

- `POST /plugins/updateView` (`src/flua/api/routes/plugins.py`) patches
  `device.view[componentName][propertyName]` — slider values included.
- `GET /plugins/getView` merges that live `device.view` back into the
  `$jason` layout (`_merge_view_state`), so a QA reading `self:getView()`
  sees the slider's updated `value` immediately.

So a QA verified in flua — e.g. `examples/proxy.lua`, whose slider handler
echoes the value back with `self:updateView("s1", "value", ...)` — behaves
in flua like the HC3's mobile view and like a reloaded classic view. It
cannot reproduce the classic-view display bug, because that bug lives in
the browser-side render, not in the API contract flua simulates.

## Impact / where to look when a user hits it

- A user who verifies the slider update in flua and then sees it frozen in
  the HC3 classic view is hitting this HC3 bug, not a flua/parity
  difference — the API state on both sides agrees.
- The proxy path is unaffected: updateView routes through the proxy QA's
  own `UPDATEVIEW` action (`plugins.py`), same channel CONNECT uses.

## Related

- `docs/rest-endpoints.md` — `/plugins/updateView` and `/plugins/getView`
  route notes.
- `examples/proxy.lua` — the slider `updateView` handler this note
  documents (works in flua + HC3 mobile view; classic view shows the bug).
