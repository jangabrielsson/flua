# Note: the HC3 hub browser in the VS Code extension (design draft)

Status: design draft, not built (2026-11-08).

## Context and goal

flua is the engine — for agent-loop development and for programmers who
want their standard toolset (VS Code, git, a debugger, tests). Wizards and
GUI conveniences are **apps built on top of flua**, and the VS Code
extension is the first such app. The discipline that keeps this true:
**nothing exists only in the app** — every tree action is a CLI/`--tool`
command first, so agents and CI get the same surface as the GUI.

This note designs the first app: an HC3 buffer in VS Code. It shows the
hub and its QuickApps; a QA can be selected, downloaded, edited (the
normal editor), tested (F5/`--ui`), and uploaded back — the whole loop
without leaving VS Code or remembering ids.

The symmetry to state up front: this tree is the *human* version of what
`flua-mcp` already gives agents (list, download, check, upload as typed
tools). Both ride the same CLI commands, so they cannot drift apart, and
the agent path stays the reference implementation.

## What exists today (verified)

- **Extension** (`vscode/src/`): commands for `downloadQA`, `uploadFile`,
  `uploadFQA`, `updateQA`, `pack`, `unpack`, `check` — all thin wrappers
  over `execFlua()` (`flua.ts`). No tree views, no data views yet.
- **flua tools**: `downloadQA` (download + unpack), `updateQA` (upload an
  unpacked project), `uploadQA`/`uploadFQA`/`uploadFile`, `pack`/`unpack`.
- **Missing piece**: there is no command that *lists* a hub's QuickApps as
  data. `doctor` checks hub reachability and reports model/firmware, but
  not the QA list.

## Design

### Data source: one new CLI command

`flua --tool hubList --json` prints a stable shape:

```json
{
  "hub": {"name": "HC3-00000422", "model": "HC3", "firmware": "5.221.22", "url": "http://192.168.1.20", "reachable": true},
  "qas": [{"id": 57, "name": "Heating", "type": "com.fibaro.deviceController", "room": "Living room"}]
}
```

- Hub info comes from the same checks `doctor` already performs
  (reachability, model, firmware) — no new hub surface.
- QAs keyed by **id**, never by name (HC3 names are not unique).
- Uses the `.env` credential chain like every other tool; without
  credentials it fails with the same clear message the other tools give.

### The tree (extension side)

One new file `vscode/src/hub.ts`, a `TreeDataProvider`:

- Root: the hub node — description carries `model · firmware ·
  reachable`, refreshed by a refresh button (and on expand). No
  background polling: the HC3 does not need flua hammering it, and a
  refresh button is predictable.
- Children: one node per QA — label `name`, description
  `id · type · room`.
- Actions on QA nodes (each maps 1:1 to an existing tool):
  - **Download & open** — `downloadQA` + unpack + open the main file in
    the editor.
  - **Update** — `updateQA` (upload the local, unpacked project).
  - **Upload as .fqa** — `uploadFQA` (fresh package).
  - **Run (UI)** — launch the workspace's existing run/debug config
    (`--tool setup` already writes them).
  - **Pack** — `pack` the unpacked project back to `.fqa`.
- The same actions land in the command palette and the QA file's context
  menu, like the current commands.
- **No delete action**: flua never deletes on the hub — deletes stay in
  the HC3 web interface (the same safety posture as every existing tool).
- Credentials: the tree only shells out to flua; the extension never
  reads or stores the password.

### Stretch (not v1)

- A devices section under the hub node (the `/devices` list, searchable —
  overlaps with the completions note's `--tool house`; reuse it).
- A hub console tail (hub debug messages, paged like the HC3 web UI).
- A local-vs-hub freshness badge on QA nodes (the unpacked folder's
  mtime vs the hub's `modified` timestamp).
- A webview dashboard (devices, console, live values) — deliberately
  second: the tree proves the shape first, and a dashboard is a much
  bigger surface.

## Alternatives considered

- **Webview dashboard first**: richer, but heavier, less native, and more
  to maintain; the tree covers the actual workflow (find → download →
  edit → upload) with plain VS Code primitives.
- **Drive it through flua-mcp**: the typed tools already exist, but the
  extension would then depend on a running MCP server; the CLI tool keeps
  the extension dependency-free and gives agents/CI the same JSON.
- **Parse `downloadQA` output**: fragile; a dedicated `--json` tool is
  the stable contract (the same reasoning as `--tool house` in the
  completions note).

## v1 scope

1. `flua --tool hubList --json` with a pinning test for the shape and
   the missing-credentials error.
2. `vscode/src/hub.ts` — the tree, refresh, and the five QA actions
   wired to the existing `execFlua` bridge.
3. Command palette + context-menu entries.
4. Docs: USAGE.md (`--tool hubList`) and the extension README.

## Related

- `docs/notes/notes-vscode-completions.md` — the other extension surface
  (the `--tool house` data source overlaps with the stretch)
- `vscode/src/flua.ts` — the `execFlua` bridge the tree rides
- `src/flua/tools/download_qa.py` / `update_qa.py` — the actions
- `docs/mcp.md` — the agent version of the same surface
