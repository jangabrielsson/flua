---
name: flua-setup
description: How to install flua, configure HC3 credentials (.env file), scaffold a new QuickApp project, VS Code integration (launch.json, tasks), and the key CLI flags and --%% directives reference. USE FOR: setting up a new flua development workspace, connecting flua to an HC3, understanding --api/--seed/--ui/--watch/--run-for flags, project scaffolding, VS Code F5 debugging setup.
---

# flua Setup and Workspace Guide

---

## Installation

**Requirements:** Python 3.11+ (`lupa` is the only runtime dependency), macOS / Linux / Windows

```bash
# Install from PyPI
pip install fibaro-flua

# Verify
flua --version
```

For development from source:

```bash
git clone https://github.com/jangabrielsson/flua.git
cd flua
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## HC3 credentials (.env)

flua reads HC3 credentials through an environment chain: the local `.env`
in the directory you run from, then `~/.env`, then the shell environment.

```bash
# .env
HC3_URL=http://192.168.1.10/
HC3_USER=admin
HC3_PASSWORD=your-password
HC3_PIN=1111
```

`HC3_URL` (or `HC3_HOST`) is required for online mode — which is the
**default** (see Modes below). A missing `HC3_URL` is a loud startup error,
and wrong credentials abort immediately (the HC3 locks itself after 4
failed attempts, so flua never retries a 401/403).

## Modes — how the emulator talks to the HC3

One directive decides it all, `--%%mode:online|offline|proxy` (placed in
the QA's header, or in a defaults file pulled in with `--%%include:<file>`):

- `--%%mode:offline` — run against the simulated HC3 only (the default; no
  credentials needed).
- `--%%mode:online` — against the real HC3 (credentials required).
- `--%%mode:proxy` — mirror the QA onto the HC3 as a `<name>_Proxy` device and
  funnel its actions/UI events back to the emulator (online only).
- `--%%mode:proxy,noUI` — proxy mode, but leave the proxy's UI untouched
  (you edit it in the HC3's own UI editor; the connect doesn't clobber it).

Resolution order: explicit `--api local|remote` flag → the main QA's
directives (over any `--%%include`'d defaults) → default offline.

## Scaffold a QuickApp project

A QuickApp is a Lua file with a `--%%` directive header:

```lua
--%%name:My QuickApp
--%%type:com.fibaro.binarySwitch
--%%u:{label="lbl",text="Status"}
--%%u:{button="btn",text="Go",onReleased="handleBtn"}

function QuickApp:onInit()
  self:debug(self.name, self.id)
end

function QuickApp:handleBtn(event)
  self:updateProperty("value", not self.properties.value)
end
```

Multi-file QAs declare their extra files in the main file:

```lua
--%%file:lib.lua,lib
--%%file:util.lua,util
```

## VS Code integration

The repo ships `.vscode/launch.json` with five configurations:

- **Flua: Run Current File** — plain run of the active `.lua` file.
- **Flua: Run Current File (Terminal)** — same, in the integrated terminal.
- **Flua: Run Current File (UI)** — run + the UI viewer in the browser.
- **Flua: Debug Current File (mobdebug)** — remote Lua debugging through the
  mobdebug protocol (the Lua extension).
- **Flua: Debug Current File (UI+mobdebug)** — debugger and viewer together.

**Lua Language Server**: `flua --tool setup` also writes a `.luarc.json`
(Lua 5.5, HC3 globals) and the **`.luals/` type library** — LuaLS definitions
for `QuickApp`, `fibaro`, `api` and `json` — so scaffolded projects get
autocomplete and parameter hints on QA code. The repo carries the same
configuration for contributors.

`setup` also installs `.vscode/tasks.json` with one task:
**Flua: Upload file to HC3** — runs `flua --tool uploadFile ${file}` on the
file you are editing, pushing just that file to its QA (the target comes
from the `--%%deviceId`/`--%%qaFile` directives `downloadQA` writes into
every unpacked file).

## Key CLI flags

| Flag | Meaning |
|---|---|
| `--api local\|remote` | force the API backend (wins over `--%%mode`) |
| `--seed house.json` | seed the simulated HC3 with devices/rooms/scenes/globals |
| `--ui [PORT]` | serve the sim API for `viewer/index.html` (stays up until Ctrl-C) |
| `--watch` | restart QAs when their files change |
| `--check` | static checks only (syntax, unknown `--%%` directives, deprecated APIs) |
| `--run-for N` | 0 = until exit(); N>0 = at least N virtual s, then exit when idle; N<0 = exactly abs(N) s |
| `--speed N` | virtual time speed (N=60 runs 60x faster) |
| `--instant` | timers fire immediately, time jumps ahead |
| `--start WHEN` | virtual start time, e.g. `2027/10/6 12:00:20` |
| `--debugger [PORT]` | attach the mobdebug remote debugger (default 8172) |
| `--color always\|auto\|never` | ANSI colors on QA log lines |

`flua export script.lua -o script.fqa` builds the HC3 deploy artifact;
`flua unpack script.fqa -d project/` reverses it.

## Key `--%%` directives

| Directive | Meaning |
|---|---|
| `--%%mode:online\|offline\|proxy` | the mode (see above) |
| `--%%name:x` / `--%%type:...` | device name / type |
| `--%%property:value=true` / `--%%properties:...` | raw device properties |
| `--%%var:name=expr` | QuickApp variable initializer (a Lua expression) |
| `--%%u:{...}` | one UI row (label/button/switch/slider/select/multi) |
| `--%%useUiView:true` | render the new `uiView` format instead of the legacy `viewLayout` (default false) |
| `--%%debug:refreshState=true,api=true,http=true` | debug logging categories |
| `--%%loglength:120` | debug line length cap (default 120) |
| `--%%keep-alive:true` | keep the online run alive past idle |
| `--%%file:path,name` | extra QA file |

A typo'd directive warns at runtime (`unknown --%% directive`) and
`flua --check` flags it with the file context.

## The `--%%include` defaults directive

A QA can pull its defaults from another file — explicit and per-QA, the
path relative to the main file (like `--%%file`):

```lua
--%%include:defaults.lua      -- the file's directives become defaults
--%%name:LocalName            -- this QA's own directives override them
```

```lua
-- defaults.lua
--%%mode:offline              # this project normally runs offline
```

The QA's own directives win per key (the mode family as a whole — a QA can
opt out of an included `--%%mode:offline`); `--%%file` lists append;
includes nest and a missing include is an error. This replaced the old
`.directives` working-directory file (ambiguous with QAs in different
subdirectories — each QA now declares its defaults explicitly).

## Working with agents

flua is developed with AI agents in the loop. The repo root carries
`AGENTS.md` (framework-agnostic agent guide: architecture map, build/test
commands, conventions) and `.github/copilot-instructions.md` plus
`.github/skills/` for GitHub Copilot in VS Code.
