# Note: hub-aware completions in the VS Code extension (design draft)

Status: design draft, not built (2026-11-08).

## Context and goal

Magic numbers are the biggest friction in `fibaro.*` calls: `fibaro.call(45,
"turnOn")` says nothing about what device 45 is. A developer in the HC3
web editor can look up the ID, but in VS Code the number is just a
number. This note designs completions that carry the data — device IDs
*with names and rooms*, global variable names, scene IDs, custom event
names, and a `HT.kitchen.light` home table — through the existing flua
VS Code extension. One edge worth claiming: the data can also come from
the **simulated house** (db/seed file), so completions work fully
offline — or for a house that does not exist yet.

## What exists today (verified)

- **Extension** (`vscode/src/`): `extension.ts` registers commands only;
  `flua.ts` provides `execFlua()` — every feature shells out to the flua
  CLI. No HTTP client, no credential handling in the extension: the CLI
  owns the `.env` chain.
- **Data surfaces in flua**:
  - Real hub (online): the `hc3.py` client — `/devices`,
    `/globalVariables`, `/scenes`, `/customEvents`.
  - Sim: the emulator serves `/devices`, `/globalVariables`, `/scenes`,
    `/customEvents` (`src/flua/api/routes/`); `--tool state` already
    loads sim state from a seed/db file.
- **LuaLS**: `--tool setup` installs LuaLS + types; a generated, typed
  Lua module in the workspace gets completions for free.

## Design

### Data source: one new CLI command

`flua --tool house --json` prints a stable shape:

```json
{
  "devices": [{"id": 45, "name": "Kitchen light", "room": "Kitchen", "type": "com.fibaro.binarySwitch"}],
  "globals": ["AlarmState", "Presence"],
  "scenes": [{"id": 3, "name": "Evening lights"}],
  "customEvents": ["DoorOpened"]
}
```

Resolution order:

1. HC3 credentials present (the `.env` chain) → fetch from the hub
   (online mode, the same path `downloadQA`/`uploadQA` use).
2. Else a db/seed file (a new `flua.houseDb` extension setting, or the
   workspace's `.flua-directives` `--%%db:`) → load the sim state, the
   same logic as `--tool state`.
3. Else empty — a QA-only run has no house, and an empty list is honest.

The tool is the single choke point: the provider never talks to a hub or
the sim directly, so credential handling and offline behavior stay in one
place (and agents/CI get the same JSON for free).

### Completions provider (extension side)

One new file `vscode/src/completions.ts`:

- `languages.registerCompletionItemProvider("lua", provider, '"', "'", ".", " ", "0".."9")`
- Context detection is a backward scan of the text before the cursor
  (line-local regexes), no AST needed for v1:
  - first argument of `fibaro.call(` / `fibaro.getValue(` /
    `fibaro.setValue(` → device items: `insertText = id`,
    `label = "45 — Kitchen light"`, `detail = room`, `filterText` includes
    the name so typing `kitchen` finds it.
  - inside `fibaro.getGlobalVariable("` / `fibaro.setGlobalVariable("` →
    global names.
  - `fibaro.scene("execute", <id>)` → scene IDs with names.
  - inside `fibaro.emitCustomEvent("` → custom event names.
- `HT.*`: **no provider needed** — a `flua.generateHomeTable` command
  writes a `---@class`-annotated `ht.lua` into the workspace (rooms →
  names → ids, plus the `HT = json.decode(fibaro.getGlobalVariable(...))`
  loader snippet). Plain LuaLS then completes
  `HT.kitchen.light`, and the table travels in the QA like any file.
- Cache: in-memory, refreshed by a `flua.refreshHouse` command and on
  extension activation; setting `flua.houseRefresh` (`onSave` | `manual`).
  Data never leaves the machine.
- Trigger caveat: numeric positions (device/scene IDs) auto-trigger less
  reliably than string positions — Ctrl+Space always works. Document it.

### Stretch (not v1)

- Live refresh against a *running* emulator (`--ui`/helper port, REST
  query) so the list tracks the run.
- A room filter and a "type icon" in the device items.
- Regenerating `ht.lua` when the house changes (save-time diff).

## Alternatives considered

- **LuaLS addon** (Lua plugin API): context-aware completions inside
  `fibaro.call` without a native VS Code provider; works in any LuaLS
  host. More moving parts (addon shipping/loading, per-workspace
  install), no access to flua settings/commands — and the extension's
  whole architecture is already `execFlua` + native providers.
- **Generated constants module** (`local DEV = {...}` or `HT` alone):
  completions only for names the user already knows to reference; no
  context awareness in calls. `HT` covers the readability goal, the
  provider covers discoverability — v1 does both but keeps them separate.

## v1 scope

1. `flua --tool house --json` (hub or db/seed) with a pinning test for
   the JSON shape.
2. `vscode/src/completions.ts` — the four contexts above.
3. `flua.generateHomeTable` + `flua.refreshHouse` commands, the
   `flua.houseDb`/`flua.houseRefresh` settings.
4. Docs: USAGE.md (`--tool house`) and the extension README.

## Related

- `src/flua/tools/state_tool.py` — the seed/db loading logic to reuse
- `vscode/src/flua.ts` — the `execFlua` bridge the provider rides
- `docs/notes/notes-mcp.md` — same design-draft style
