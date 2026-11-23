# 0016 — a web UI builder for `--%%u` / `--%%rsrc`

- Status: **proposed** (draft for discussion)
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

`flua --tool uibuilder [PORT]` serves a page in the same style as the UI
viewer. The editor model is **the row JSON** the directives parse to —
no new format.

- **Palette** — the element set with a v1/v2 toggle: v1 = label, button,
  slider, switch, select, multi; v2 adds tabView, collapsible, image
  (v2-only elements marked; adding one hints `--%%useUiView:true`).
- **Properties** — one form per element: name, text, callbacks
  (`onReleased`, `onChanged`, `onToggled`, `onTabChanged`, …), min/max/
  value, options, values, url — the fields the compiler understands.
- **Row editor** — add/remove/reorder rows; several elements share a row;
  tabView/collapsible bodies edited as nested rows.
- **Live preview** — the server compiles the rows through `compile_ui`
  (and `child_bindings` for a child target) and the preview pane reuses
  the viewer's `renderComponent`, so what you see is what the HC3
  renders. Preview interactions are local/inert (no QA behind the page).
- **Export pane** — copy buttons for the three target forms: `--%%u`
  lines (main QA), `--%%rsrc:<name>:{…}` (child resource), and the raw
  Lua table (`--as-lua` shape).
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

## Open questions

1. Standalone `--tool uibuilder` vs. an edit mode inside `--ui`? (Leaning
   standalone — separate page, same server machinery.)
2. Export set: all three forms from the start, or `--%%u` + `--%%rsrc`
   first and the Lua table behind a toggle?
3. Should the child/mode target (child bindings vs. main-QA bindings) be
   a top-level switch in the builder?
