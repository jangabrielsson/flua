# flua for VS Code

HC3 QuickApp support for VS Code: drive [flua](https://github.com/jangabrielsson/flua)
from the explorer, get QA findings in the Problems panel, and read `.fqa`
packages without unpacking them by hand.

## Requirements

- [flua](https://github.com/jangabrielsson/flua) installed (a workspace
  `.venv` is auto-detected; otherwise `flua` on PATH, or set
  `flua.executable`).
- Recommended companions (installed for you by `flua --tool setup`'s
  `.vscode/extensions.json`): **Lua Language Server** (autocomplete via the
  `.luarc.json` + `.luals/` setup writes), **Lua MobDebug** (breakpoints via
  the launch configs), **Python**.

## Features

- **Explorer context menu → flua** (right-click a file):
  - `Pack QA into .fqa` (`.lua`) — `flua --tool pack`
  - `Unpack .fqa into project` (`.fqa`) — `flua --tool unpack`
  - `Upload file to HC3 QA` (`.lua`) — `flua --tool uploadFile`
  - `Upload .fqa as new QA` (`.fqa`) — `flua --tool uploadFQA`
  - `Update QA on HC3` (`.lua`, asks for the QA id) — `flua --tool updateQA`
  - `Download QA from HC3` (asks for the QA id) — `flua --tool downloadQA`
  - `New QA from template` — Quick Pick over the 41 device type templates
  - `Setup workspace` — `flua --tool setup`
- **Check on save**: saving a `.lua` file runs `flua --check --json`; syntax
  errors, unknown `--%%` directives, plua-style directive typos, and
  deprecated REST endpoints appear in the Problems panel (findings for
  `--%%file` includes land on those files).
- **Onboarding nudge**: a workspace with Lua files but no HC3 completion
  config (`.luarc.json`/`.luals`) gets a one-time offer to run Setup
  workspace (`flua.setupNudge` turns it off).
- **MCP registration**: "Flua: Register flua-mcp with Copilot" writes the
  flua-mcp stdio server into the workspace's `.vscode/mcp.json` — the venv
  python interpreter with `-m flua.mcp.server`, exactly as `docs/mcp.md`
  documents — leaving other servers untouched; "Unregister" removes it.
- **`.fqa` packages open in the flua QA editor**: the package summary
  (name, type, interfaces) plus the packed metadata — properties like
  `manufacturer`/`userDescription`, `quickAppVariables` one per line, and
  a collapsed UI summary — with a syntax-highlighted Lua preview per file
  and Unpack / Upload buttons. The raw JSON stays available via "Reopen
  Editor With… Text Editor", validated against flua's package schema.

Tool commands run in the shared **flua terminal** (`flua.runToolsInTerminal`
switches to the output channel) so interactive HC3 credential prompts work.

## Development

```bash
cd vscode
npm install
npm run compile        # tsc
npm run package        # build the .vsix (needs @vscode/vsce)
```

Debug with F5 inside this folder (launch config `Extension` — add one via
`.vscode/launch.json` if you want; `--extensionDevelopmentPath` is standard).

## Publishing

The extension is published as `GsonSoft-development.flua` — install it from
the VS Code marketplace. Its version tracks the flua release (`release.sh`
bumps `package.json` alongside the Python version, and refuses to run when
they drift).

Publishing is automated: the **Publish VS Code Extension** GitHub workflow
fires on every GitHub release (and manually via `workflow_dispatch`) and
runs `vsce publish` with the `VSCE_PAT` repository secret. The secret must
be an **organization-scoped** marketplace PAT — created in
`dev.azure.com/<org>` → user settings → Personal access tokens, scope
`Marketplace → Manage`, organization set to your own (NOT "All accessible
organizations"): *global* PATs retire in January 2027 (postponed from the
original December 1, 2026 date), while org-scoped PATs remain supported.

Manual publish from a dev machine works the same way:

```bash
cd vscode && VSCE_PAT=<org-scoped-pat> npx @vscode/vsce publish
# or once: npx @vscode/vsce login GsonSoft-development  (stores the PAT)
```

The planned successor is secretless publishing via the Entra ID credential
flow (`vsce publish --azure-credential` with workload identity federation) —
it needs an Azure subscription for the managed identity, so it is on hold
until one exists.

The extension has no runtime dependencies — it shells out to the `flua`
executable.

## Settings

- `flua.executable` — path to flua; empty = auto-detect.
- `flua.runToolsInTerminal` — run tools in the integrated terminal (default
  true) or the flua output channel.
