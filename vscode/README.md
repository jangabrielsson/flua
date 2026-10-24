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

1. Set your marketplace publisher id in `package.json` (`"publisher"`).
2. `npm run publish` (or `npx @vscode/vsce package` for a local `.vsix`).

The extension is versioned with the flua repo and has no runtime
dependencies — it shells out to the `flua` executable.

## Settings

- `flua.executable` — path to flua; empty = auto-detect.
- `flua.runToolsInTerminal` — run tools in the integrated terminal (default
  true) or the flua output channel.
