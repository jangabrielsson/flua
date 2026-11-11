# Note: HC3 upload mangles custom UI handler names (field report + fix)

Status: fixed (2026-11-11) — a user's QA, packed by flua and uploaded to
the HC3, had every button's custom handler replaced by the HC3's generated
default: button `b2` with `onReleased='zoneDownButton'` came up on the
controller as `onReleased='uib2OnReleased'` (`ui<element><eventType>`),
and taps logged "Class does not have uib2OnReleased function defined —
action ignored".

## The diagnosis chain

1. **flua's package carried the right names** — `uiCallbacks` with
   `zoneDownButton`; verified in the packed .fqa.
2. **The HC3's runtime dispatches through the stored uiCallbacks.** The
   descrambled fengari runtime (`dev/fengari_runtime.formatted.lua`)
   builds `UICB[name .. "|" .. eventType] = callback` and calls
   `qa[cb]` — no name generation there.
3. **The HC3's import regenerates uiCallbacks when the package carries a
   uiView.** Live-verified by downloading device 4441's stored package
   after upload: the viewLayout was byte-identical to what flua packed
   (element `onReleased` fields intact, and the HC3 even propagated them
   onto its uiView components), but `uiCallbacks` had been rebuilt —
   every custom callback replaced by the generated `ui<name><event>`
   default, long-press/onToggled entries dropped.
4. **The HC3's own legacy export carries no uiView.** The control
   experiment: `testQAs/HC3_Diagnostics_V2.10.fqa`, a QA exported from a
   real HC3, contains only `viewLayout` + `uiCallbacks` (custom names) —
   and such packages import with their handlers intact. flua's package
   always included the compiled `uiView` (both structures are generated
   at load); the HC3 import, seeing the uiView, took the uiView path and
   re-derived uiCallbacks from the bindings with generated defaults,
   discarding the package's table.

## The fix

`qa_export` now matches the HC3's standard legacy shape: when
`useUiView` is false, the package carries `viewLayout` + `uiCallbacks`
and **neither `uiView` nor `useUiView`** — the same shape the HC3's own
export produces, so custom handler names survive import and the package
works for anyone who installs it. The uiView format travels only when it
is the active one (`--%%useUiView:true`).

Also kept (first attempt at the fix, still valuable): `compile_ui` packs
each declared event target onto the legacy viewLayout element itself, and
the inverse converter (`ui_to_u_rows`, used by downloadQA/`--tool ui
--device`) reads element-declared targets before the uiCallbacks mirror —
so a device whose callbacks were mangled by an earlier upload still
exports its handlers from the element fields (the HC3 preserved those).

Pinned by `tests/test_tools.py::test_pack_legacy_ui_matches_the_hc3_export_shape`,
`tests/test_ui.py::test_legacy_layout_carries_event_bindings`, and
`test_legacy_layout_events_roundtrip_without_ui_callbacks`.

## Open verification

- The uiView-active case (`--%%useUiView:true`) is unverified on the
  HC3: packages carry uiView there, and the import may apply the same
  regeneration. No live evidence either way yet.
- A re-upload of the user's QA with the standard-shape package is the
  live confirmation of the fix.
