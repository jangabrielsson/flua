# AGENTS.md — Fibaro QuickApp development with flua

Guidance for AI agents (Copilot, Claude Code, Codex, Cursor, or plain LLM
tooling) working on QuickApp code in this project. Humans: see
`flua --help` and the user guide at
https://github.com/jangabrielsson/flua/blob/main/USAGE.md

## What this project is

Lua QuickApps for a Fibaro HC3 controller. The files run **unchanged** on
the HC3 and in the flua emulator — the same QA file works in both places.

- Run a QA: `flua qa.lua` (defaults to online mode when HC3 credentials
  exist; `--api local` or `--%%mode:offline` for the simulated HC3).
- Static check: `flua --check qa.lua` (no execution).
- `--%%` directives in the file header drive flua (mode, db, name, type,
  variables, UI); the HC3 ignores them.

## Rules of thumb

- QuickApps are single-file Lua programs; `QuickApp:onInit()` is the entry
  point, actions are `QuickApp:<method>` methods called through
  `fibaro.call` or the UI.
- Preserve HC3 compatibility: `api.*`/`fibaro.*` calls are the controller's
  own REST surface — don't invent endpoints.
- Use `--%%db:file.json` (+`--%%db:+file.json`) to seed/persist emulator
  state; a QA's own variables should be `self:setVariable` (quickApp
  variables), not globals.
- Examples live in the flua repo's `examples/` directory — copy the pattern
  closest to the task instead of writing from scratch.

## Agent skills

This project ships Copilot skills under `.github/skills/` (flua-setup,
quickapp-api, quickapp-patterns, quickapp-types, hc3-rest-api,
flua-troubleshooting, ...). Use them when their descriptions match the
task; `.github/copilot-instructions.md` and
`.github/instructions/quickapp-dev.instructions.md` apply to all `*.lua`
work.

## Tests

QuickApp projects are usually QA files, not test suites. When a change
needs verification, prefer a small terminating QA that prints its results
and run it with `flua --api local qa.lua`.
