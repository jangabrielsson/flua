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
3. **The HC3's import re-derives uiCallbacks when the package deviates
   from the HC3's own export shape.** Live-verified by downloading device
   4441's stored package after upload: the viewLayout was byte-identical
   to what flua packed (element `onReleased` fields intact, and the HC3
   even propagated them onto its uiView components), but `uiCallbacks`
   had been rebuilt — every custom callback replaced by the generated
   `ui<name><event>` default, long-press/onToggled entries dropped.
4. **The control experiment:** `testQAs/HC3_Diagnostics_V2.10.fqa`, a QA
   exported from a real HC3, imports with its custom handlers intact.
   Its shape differs from what flua packed in three ways, all fixed
   across the three upload rounds that still mangled:
   - flua packed **`uiView`** for a legacy QA (round 1) — the HC3's
     legacy export carries none;
   - flua packed **`onReleased` etc. on the legacy viewLayout elements**
     (round 2–3) — the HC3's export elements carry no event fields (the
     binding lives in uiCallbacks only);
   - flua packed **`typeTemplateInitialized: false`** (all rounds) — the
     HC3's export carries true; false makes the import re-run its
     type-template initialization, which is what re-derives uiCallbacks
     with generated defaults.

## The fix

`qa_export` now emits the HC3's own legacy export shape byte-for-byte on
every axis: `viewLayout` + `uiCallbacks` only (no `uiView`, no
`useUiView`, no event fields on the elements), `typeTemplateInitialized:
true`, and empty `userDescription`/`initialInterfaces` omitted. The
uiView format travels only when it is the active one
(`--%%useUiView:true`).

`ui_to_u_rows` (downloadQA/`--tool ui --device`) still reads
element-declared event fields first — real HC3 devices carry them after
an editor save — so a device whose callbacks were mangled by an earlier
upload still exports its handlers from the element fields (the HC3
preserved those).

Pinned by `tests/test_tools.py::test_pack_legacy_ui_matches_the_hc3_export_shape`,
`tests/test_ui.py::test_legacy_layout_has_no_event_fields`, and
`test_legacy_layout_events_roundtrip_without_ui_callbacks`.

## Open verification

- A re-upload of the user's QA with the 0.1.148-shape package is the
  live confirmation.
- The uiView-active case (`--%%useUiView:true`) is unverified on the
  HC3: packages carry uiView there, and the import may apply the same
  re-derivation. No live evidence either way yet.
