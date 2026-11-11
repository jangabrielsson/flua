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
3. **The mangling is a property of the API-create endpoint, not the
   package.** Four package-shape variants were uploaded via
   `POST /quickApp` (flua's uploadFQA/uploadQA) — all mangled; the
   controller also converted the UI to uiView and set `useUiView: true`
   during import. Meanwhile, the same HC3 holds QAs with intact custom
   callbacks (the Dirigera QA, and the proxy QA which re-applies
   uiCallbacks via updateProperty after deploy).
4. **The decisive test: the HC3 web UI's Import button.** Importing the
   same .fqa through the web UI preserved every custom handler name. The
   browser posts to **`POST /quickApp/import`** as `multipart/form-data`
   with a `file` field (+ optional `roomId`) — a different pipeline than
   the JSON `POST /quickApp` API-create, which re-derives uiCallbacks
   from its converted UI model with generated defaults regardless of the
   package's contents.

## The fix

- `Hc3Remote.multipart()` — the web UI's wire format (multipart/form-data,
  `file`/`roomId` fields, `X-Fibaro-Version: 2` like the browser's
  interceptor). The `file` part must carry a **filename** — a
  filename-less part crashes the HC3's import handler with a bodyless
  HTTP 500 (live-verified; the browser uploads a File, so its part always
  has one).
- Every QA-create path in flua now uses `POST /quickApp/import` against a
  real HC3: `uploadFQA`, `uploadQA` (new-QA path), `installHelper`, and
  the proxy deploy. The offline sim keeps the JSON `POST /quickApp` path
  (the sim never re-derives). `parity_capture` deliberately stays on the
  JSON create — it pins that endpoint's contract for the parity suite.
- Live-verified on HC3 firmware **5.221.22 (beta)**: a tool upload stored
  all 23 custom callbacks intact on the controller. The re-derivation is
  recent-firmware behavior — plausible it did not exist in older 5.2xx
  builds, which would explain why QAs uploaded through the API years ago
  still work while new uploads broke.

### Why the proxy never showed the problem

Two reasons, both visible in the code:

1. **The proxy's dispatch bypasses uiCallbacks.** `onUIEvent` in the
   runtime (the HC3 plua contract flua ports) checks
   `quickApp.UIHandler` FIRST — the proxy shim defines
   `QuickApp:UIHandler(ev)` and forwards every UI event to the emulator
   over HTTP, so the mangled uiCallbacks table is never consulted.
2. **The mirror re-syncs the UI properties anyway.** On proxy runs flua
   PUTs the correct `viewLayout`/`uiView`/`uiCallbacks` to the HC3 device
   (`sync_proxy_ui`), overwriting the import's mangled table — which is
   why the proxy device's stored properties always looked intact.

Also kept from the earlier rounds (export-shape parity, harmless and
matching the HC3's own exports): `qa_export` emits `viewLayout` +
`uiCallbacks` only for legacy QAs (no uiView/useUiView), no event fields
on the elements, `typeTemplateInitialized: true`, empty
userDescription/initialInterfaces omitted. These were not the trigger,
but they make flua's packages byte-shape-identical to an HC3 export.

Pinned by `tests/test_tools.py::test_upload_fqa_uses_the_web_import_endpoint`
and the pack-shape tests from the earlier rounds.

## Open verification

- The uiView-active case (`--%%useUiView:true`) — unverified on the HC3,
  but the import endpoint preserves the package verbatim so the same fix
  covers it.
- The proxy's deploy still uses JSON `POST /quickApp` and repairs
  uiCallbacks via updateProperty afterwards — works today; could switch
  to the import endpoint for parity.
