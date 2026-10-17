# Note: single-select initial `value` dropped from legacy viewLayout

Status: fixed (2026-10-17). The compiler maps `el['value']` into the
legacy `values` array, and the inverse (`ui_to_u_rows`/`_element`) reads
the selection back — the `--%%u` round trip now preserves it.
Pinned by `tests/test_ui.py::test_select_with_options` (legacy values +
round trip) and `tests/test_agent_dx.py::test_tool_ui_renders_elements`
(`--tool ui` shows the selection).

## Symptom

A single `select` row declared with an initial value —

```lua
--%%u:{select='sel1',text='Pick',value='11',options={{type='option',text='One',value='11'}}}
```

— exports a legacy `viewLayout` (`$jason`) component whose selection is
empty:

```json
{"type": "select", "selectionType": "single", "options": [...], "values": []}
```

The initial `value='11'` is gone. `--tool ui` shows the select with no
selection; more importantly, the compiled viewLayout a viewer or an HC3
upload renders starts unselected.

## Root cause

`src/flua/ui.py::_layout_element` — the select/multi branch maps only
`el.get("values")` (the multi-select field) into `component["values"]`. The
single-select convention's `el["value"]` is never read for the legacy
format. The newer `uiView` format (`_ui_view`) does carry it
(`component["value"]`), so this is legacy-format-only.

## Ground truth (why it matters)

The HC3's own schema (`fibaro_api_docs/plugins.json`, the `select`
component) has no `value` field at all — the current selection lives in
`values`, documented as "List of selected options", even for
`selectionType: single`. So the legacy format's selected state IS `values`,
and flua should map the row's initial `value` into `values: ["11"]`.

## Fix sketch (when we pick this up)

In `_layout_element`, the `typ in ("select", "multi")` branch:

```python
if typ == "select" and el.get("value"):
    component["values"] = [el["value"]]
else:
    component["values"] = list(el.get("values") or [])
```

Then check the round trip: `ui.py::_rows_from_view_layout` reads `values`
back into `--%%u` rows — a single select should come back as
`values={'11'}` (not `value='11'`), so `--%%u` select rows may need to
accept both spellings. Verify against the HC3: an uploaded QA should show
the option selected in the web UI. Also re-check `singleSelectDemo.lua` and
the multiSelect work (selectedItems/updateView) from 2026-10-06, which
touched exactly this area.

## Related

- `--tool ui` renders whatever the compiled structures contain, so it
  shows the gap (select with no selection) rather than hiding it.
- The uiView format (used with `--%%useUiView:true`) is unaffected.
- `docs/notes-agents.md` ("Known gaps") references this note.
