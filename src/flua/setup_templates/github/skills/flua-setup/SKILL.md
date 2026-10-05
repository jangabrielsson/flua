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
the QA's header, or as a default in a `.directives` file in the working
directory):

- `--%%mode:offline` — run against the simulated HC3 only (no credentials needed).
- `--%%mode:online` — the default: online against the real HC3.
- `--%%mode:proxy` — mirror the QA onto the HC3 as a `<name>_Proxy` device and
  funnel its actions/UI events back to the emulator (online only).

Resolution order: explicit `--api local|remote` flag → the main QA's
directives (merged over the `.directives` defaults) → default online.

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

The repo ships `.vscode/launch.json` with three configurations:

- **Flua: Run Current File** — plain run of the active `.lua` file.
- **Flua: Run Current File (Terminal)** — same, in the integrated terminal.
- **Flua: Debug Current File (mobdebug)** — remote Lua debugging through the
  mobdebug protocol (the Lua extension).

Tasks in `.vscode/tasks.json` cover `--check`, `.fqa` export and unpack.

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

## The `.directives` defaults file

A `.directives` file in the working directory supplies defaults for the
main QA (same `--%%` syntax; the QA's own directives override). The usual
content: a default mode and log/trace defaults.

```
# .directives — defaults for the main QA
--%%mode:offline      # this project normally runs offline
```

## Working with agents

flua is developed with AI agents in the loop. The repo root carries
`AGENTS.md` (framework-agnostic agent guide: architecture map, build/test
commands, conventions) and `.github/copilot-instructions.md` plus
`.github/skills/` for GitHub Copilot in VS Code.
