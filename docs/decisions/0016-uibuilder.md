# 0016 — a web UI builder for `--%%u` / `--%%rsrc`

- Status: **accepted** (design settled, not yet built)
- Date: 2026-11-23

## Context

Child devices are the one place on the HC3 where modern view elements
(`tabView`, `collapsible`) are safe — the editor never rewrites a child's
uiView. But that safety comes with a cost: there is *no HC3-side tool* to
author those UIs, so today they are written as `--%%u`/`--%%rsrc` rows by
hand (or pasted from `--tool ui --as-lua`). flua already owns the entire
compile chain — rows → `uiView`/`viewLayout`/`uiCallbacks`, the inverse
(`ui_to_u_rows`), `lua_literal`, `child_bindings`, `--%%rsrc` — and its
web viewer already renders the uiView faithfully. The missing piece is
authoring: a visual builder that emits the directives.

## The shape

`flua --tool uibuilder [PORT]` serves a standalone page in the same style
as the UI viewer. The editor model is **the row JSON** the directives
parse to — no new format.

- **Target selector** (the top-level switch, replacing a naive v1/v2
  toggle):
  - **Main QA — v1**: the legacy format. Elements: label (HTML text
    allowed — the v1 reason to exist), button, slider, switch, select,
    multi. No v2-only elements. Export: `--%%u` lines (legacy package).
  - **Main QA — v2**: the uiView format. Full element set (adds
    `tabView`, `collapsible`, `image`), `UIAction` bindings. Export:
    `--%%u` lines + the `--%%useUiView:true` hint.
  - **Child device**: children carry a uiView only — the v1/viewLayout
    question does not apply. Full element set, **child bindings**
    (`actionName` = the method, `json.array()` for argless). Export:
    `--%%rsrc:<name>:{…}` (the resource form; a name field in the UI).
- **Palette** — the elements the selected target allows; v2-only elements
  are marked and disabled for Main-v1.
- **Properties** — one form per element: name, text, callbacks
  (`onReleased`, `onChanged`, `onToggled`, `onTabChanged`, …), min/max/
  value, options, values, url — the fields the compiler understands. For
  the Child target, callbacks are the child class's method names.
- **Row editor** — add/remove/reorder rows; several elements share a row;
  tabView/collapsible bodies edited as nested rows.
- **Live preview** — the server compiles the rows through `compile_ui`
  (plus `child_bindings` for the Child target) and the preview pane
  reuses the viewer's `renderComponent`, so what you see is what the HC3
  renders, bindings included. Preview interactions are local/inert (no QA
  behind the page).
- **Export pane** — copy buttons for the directive forms first
  (`--%%u` and/or `--%%rsrc` per target); the raw Lua table
  (`--as-lua` shape) later, behind a toggle.
- **Import** — paste existing `--%%u`/`--%%rsrc` back into the model
  (the parser already exists).

## Reuse

- Server side: two small HTTP routes — compile rows → uiView (preview)
  and parse pasted directives → rows. Everything else exists.
- Client side: the viewer's `renderComponent`/`appendRows` for the
  preview; the page/theme conventions of the viewer.
- No new format, no new compiler, no persistence.

## Non-goals

- No editing of running QAs, no HC3 upload (export/uploadQA exist).
- No pixel-perfect WYSIWYG; no drag-and-drop beyond row reordering.
- No file writing — copy-paste into source is the contract; the builder
  is stateless.

## Decisions

1. Standalone `--tool uibuilder` (not a mode inside `--ui`).
2. Export the directive forms first (`--%%u` / `--%%rsrc`); the raw Lua
   table comes later behind a toggle.
3. The binding/format choice is a three-way **target**, not a v1/v2
   element toggle: the uiView format is the same everywhere; what differs
   is the binding target (main QA `UIAction` vs. child `actionName`) and
   the one format a child cannot have (viewLayout/v1).
