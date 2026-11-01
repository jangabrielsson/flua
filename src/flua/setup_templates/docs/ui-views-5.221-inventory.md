# HC3 5.221.21 UI views — inventory vs flua's viewer

What the new firmware's UI layer exposes, extracted from the rootfs dump
(`/opt/fibaro/ui-views` — the view definitions, `types/` + `interfaces/`
and the newer `v2/` variants; `/var/www/plugins` — the built-in plugin
QAs' JSON views). Prepared for the "what should our web viewer support"
discussion.

## The two directories

- **`opt/fibaro/ui-views/{types,interfaces}` + `v2/…`** — the HC3's own
  view definitions: per-device-type views (`com.fibaro.rollerShutter.json`
  …) assembled from **composable interface fragments**
  (`advancedSlats`, `favoritePosition`, `lockSpring`, `manualMode`,
  `partialOpen`, `stepByStep`, …) via `{type:"include", interface:…}`.
  The `v2/` tree is the newest format (colorController, hvacSystem,
  weather, sensor are v2-only).
- **`var/www/plugins`** — the built-in plugin QAs' views as JSON (the
  shipped-UIs, one directory per `com.fibaro.*` type).

## What the v2 schema contains (full scan)

Element types in use (counts over all 40+ files):

| type | count | notable properties |
|---|---|---|
| button | 184 | text, visible, `image` (named icons: chevronDown, dashedUp…), `classes`, style.weight |
| slider | 54 | min/max/step, `unit`, `value` (`{{device.properties.x}}` templated), classes |
| switch | 19 | value, `disabled`, `hint`, `image`, classes |
| select | 3 | options, `selectionType`, `values`, text |
| label | 8 | text, visible |
| colorPicker | 2 | `colorSpace`, `channels` (red/green/blue → templated colorComponents) |
| colorTemperaturePicker | 4 | colorTemperature, min/maxTemperature |
| tabView + tab | 15 | `activeTab`, `tabs[]` (tab: text, image, classes) |
| horizontal/vertical/space | 124 | layout containers |
| nativeComponent | 3 | app-provided views (weather, hvacSystem, sensor) — nothing to render server-side |

Events (eventBinding keys):

- `onReleased` (202), `onChanged` (60), `onLongPressDown`/`onLongPressReleased` (22+22) — buttons and sliders
- `onToggled` (3), plus new split `onToggleOn`/`onToggleOff` — switches
- events bind to **declarative actions**, not QA callbacks:
  `deviceAction` (`{actionName, args:["$event.value"]}`),
  `updateDeviceProperty`, `updateClientView` — with `$event` templating.

## What this means vs flua today

- **flua's `--%%u` already has**: button (incl. long-press callback names
  in `compile_ui`), slider, switch, select, multi, label. The VIEWER only
  renders/emits onReleased/onToggled/onChanged — **long-press and the
  toggle-split events exist in the schema but the viewer neither renders
  nor sends them**.
- **Genuinely new widgets**: colorPicker, colorTemperaturePicker,
  tabView/tab. Niche but real (colorController QAs, tabbed settings UIs).
- **New properties on existing elements**: `image` (named icons — we
  already ship the icon catalog!), `classes`, switch `disabled`+`hint`,
  slider `unit`, select `selectionType`+`values`.
- **The architectural shift**: views are now DECLARATIVE — `eventBinding`
  maps events to device actions/property updates with `$event` args, and
  values bind to device properties via `{{device.properties.x}}`. The QA
  no longer needs a uiCallback for standard behaviors. flua handles the
  equivalent for device-type embedded UIs (the QA_types_ui actions), but
  the `uiView`/`viewLayout` JSON is not executed as such.

## Viewer support — status

Items 1–3 SHIPPED (2026-11-01): the viewer emits
`onLongPressDown`/`onLongPressReleased` (press-and-hold, custom buttons),
switches emit `onToggleOn`/`onToggleOff` when declared (replacing the
legacy event), and buttons/switches render the named `image` icons via a
curated inline-SVG map. `compile_ui` passes the new element properties
through (`image`, `hint`, `disabled`, slider `unit`) and emits the split
toggle callbacks/bindings — pinned by `tests/test_ui.py`.

## Viewer support proposals (remaining, for discussion)

1. **Long-press on buttons** (high, small) — press-and-hold gesture in the
   viewer emitting `onLongPressDown`/`onLongPressReleased`; the schema
   and `compile_ui` already agree on the names.
2. **`onToggleOn`/`onToggleOff`** (high, trivial) — emit them from switch
   flips alongside onToggled.
3. **Named `image` icons on buttons/switches/tabs** (medium) — we already
   have the icon pipeline (`--tool icons`, the manifest); rendering the
   named icons is a lookup, not new artwork. Enables the HC3's chevron/
   arrow button UIs to look right.
4. **Declarative `eventBinding` execution** (medium-high, the interesting
   one) — the sim could execute `deviceAction`/`updateDeviceProperty`
   bindings from the view JSON, so a QA ported from the new firmware runs
   without callback shims. Worth scoping carefully: the sim already has
   the action-routing machinery; the binding is a translation layer.
5. **colorPicker / colorTemperaturePicker / tabView** (low-medium) — new
   renderers; only when a real QA needs them.
6. **`classes`, `disabled`, `hint`, `unit`, `selectionType`** (low) —
   cosmetic/validation; support cheaply as passthrough properties and let
   the viewer map the few classes it knows.

Not worth server-side work: `nativeComponent` (the app provides it —
   nothing to render), the `interfaces/` composition format itself (that is
   the HC3's internal authoring layer; flua consumes the COMPILED view,
   not the fragments).
