# Note: HC3 upload mangles custom UI handler names (field report + fix)

Status: fixed (2026-11-11) — a user's QA, packed by flua and uploaded to
the HC3, had every button's custom handler replaced by the HC3's generated
default: button `b2` with `onReleased='zoneDownButton'` came up on the
controller as `onReleased='uib2OnReleased'` (`ui<element><eventType>`).

## The diagnosis chain

1. **flua's package was correct.** The .fqa carried
   `uiCallbacks: [{name: "b2", eventType: "onReleased", callback:
   "zoneDownButton"}]` — verified directly.
2. **The HC3's runtime dispatches through the stored uiCallbacks.** The
   descrambled fengari runtime (`dev/fengari_runtime.formatted.lua`) builds
   `UICB[name .. "|" .. eventType] = callback` and calls
   `qa[cb]` — no name generation there.
3. **The HC3's canonical UI form carries the binding on the element.**
   The official docs (firmware 5.030, controls support): "Events are
   visible in the control's edit mode. You can enter name of the method
   from QuickApp class, that should handle the event." `uiCallbacks` is
   the runtime mirror of the elements, and the HC3's own UI compiler
   (`UI2uiCallbacks` in the qwikchild/UI library) derives the table FROM
   the elements.
4. **flua's legacy viewLayout elements carried no event fields** — the
   port's `mkViewLayout` only emitted name/visible/style/text/type. On
   import the HC3 re-derives uiCallbacks from the elements; every missing
   binding gets the generated default `ui<name><event>` — which clobbers
   the uploaded custom names. Buttons then call nonexistent methods and
   the QA log says "The UI calls QuickApp:uib2OnReleased(), but it
   doesn't exist".

## The fix

`compile_ui` now packs each declared event target **twice**: into
`uiCallbacks` (unchanged — the runtime mirror) **and** onto the legacy
`viewLayout` element itself (`onReleased`/`onLongPressDown`/
`onLongPressReleased` on buttons and switches, the 5.221 split
`onToggleOn`/`onToggleOff` on switches, `onChanged` on sliders,
`onToggled` on selects — undeclared events stay absent). The inverse
converter (`ui_to_u_rows`, used by downloadQA/`--tool ui --device`) reads
element-declared targets first and falls back to uiCallbacks, so devices
whose callbacks were mangled or dropped still export their handlers.

Pinned by `tests/test_ui.py::test_legacy_layout_carries_event_bindings`
and `test_legacy_layout_events_roundtrip_without_ui_callbacks`.

## Open verification

The fix is inferred from the HC3's documented canonical form and its
runtime code, and from the user's observation of the mangled result. The
user's HC3 (device 4440) has not been re-tested with a re-packed upload —
worth confirming the custom names now survive on the controller.
