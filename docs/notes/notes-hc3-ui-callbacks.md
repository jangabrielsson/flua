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
3. **The actual trigger: `initialProperties.apiVersion`.** The HC3's
   JSON create (`POST /quickApp`) decides the package's format by that
   field. WITHOUT it, the package is treated as legacy: the controller
   converts the UI to uiView (useUiView becomes true) and re-derives
   uiCallbacks with generated default names. WITH it (`"1.3"`) the
   create preserves the package verbatim. Live-verified by bisection on
   5.221.22: `UP.fqa + apiVersion` survives the JSON create; the same
   package without it mangles. Headers (including plua's full set +
   Fibaro-User-PIN), Host header, trailing slash, useUiView/uiView,
   typeTemplateInitialized and useEmbededView were all probed and ruled
   out. plua worked all along because its fqa builder copies `apiVersion`
   into initialProperties — its packages carried the marker, flua's
   didn't.
4. **The web UI's Import button** (`POST /quickApp/import`, multipart)
   preserves ANY package — that is a separate pipeline, which is why the
   tools switching to it also fixed the symptom (and remains the tools'
   path).

## The fix

- **`qa_export` carries `initialProperties.apiVersion: "1.3"`** — the
  real fix: any importer that posts the .fqa to the JSON create preserves
  it, including a QA doing a plain
  `api.post("/quickApp/", json.encode(fqa))` — no multipart needed.
- The tools also use `POST /quickApp/import` (multipart, `file` part with
  a **filename** — a filename-less part crashes the handler with a
  bodyless 500, live-verified) — belt-and-braces plus web-UI parity.
  Every QA-create path goes through it: uploadFQA, uploadQA (new QA),
  installHelper, proxy deploy. The offline sim keeps the JSON create (the
  sim never re-derives).
- The sim parses the multipart import format too (`_fqa_from_multipart`
  + the ApiServer's multipart passthrough) and offline loopback
  `127.0.0.1:11111` rewrites to the sim's `--ui` server, so both
  install flows are testable in the emulator. The sim's JSON create also
  imports `.fqa` bodies (raw or `{file: base64}`) like the real HC3, and
  warns when a QA installs a package WITHOUT the apiVersion marker (the
  real HC3 would re-derive its callbacks).

### The import endpoint's parser is strictly multipart

A raw JSON .fqa body at `POST /quickApp/import` dies with HTTP 500
`{"reason":"Network error","message":"Field name too long"}` — the handler
parses ANY body as multipart form fields (live-verified). So the
multipart recipe (quickapp-patterns skill) is for packages WITHOUT
`initialProperties.apiVersion`; with the marker, plain `api.post` to
`/quickApp/` suffices.

### Why the proxy never showed the problem

Two reasons, both visible in the code:

1. **The proxy's dispatch bypasses uiCallbacks.** `onUIEvent` checks
   `quickApp.UIHandler` FIRST — the proxy shim defines
   `QuickApp:UIHandler(ev)` and forwards every UI event to the emulator
   over HTTP, so the uiCallbacks table is never consulted.
2. **The mirror re-syncs the UI properties anyway.** On proxy runs flua
   PUTs the correct `viewLayout`/`uiView`/`uiCallbacks` to the HC3 device
   (`sync_proxy_ui`), overwriting the import's mangled table.

Also kept from the earlier rounds (export-shape parity, harmless):
`qa_export` emits `viewLayout` + `uiCallbacks` only for legacy QAs (no
uiView/useUiView), no event fields on the elements,
`typeTemplateInitialized: true`, empty userDescription/initialInterfaces
omitted. None of these were the trigger, but they keep flua's packages
close to the HC3's own export shape.

Pinned by `tests/test_tools.py::test_upload_fqa_uses_the_web_import_endpoint`,
`test_pack_legacy_ui_matches_the_hc3_export_shape` (apiVersion asserted),
and the ui_server loopback/multipart tests.

## Open verification

- The uiView-active case (`--%%useUiView:true`) — the apiVersion marker
  applies the same way; not separately probed.
- The proxy's deploy still uses JSON `POST /quickApp` and repairs
  uiCallbacks via updateProperty afterwards — with the apiVersion marker
  its create would now also preserve; switching is optional parity.
