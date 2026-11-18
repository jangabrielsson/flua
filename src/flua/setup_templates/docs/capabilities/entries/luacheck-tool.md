---
id: luacheck-tool
topic: tooling
title: The luacheck tool — a linter over the QA's file closure
pins:
  - tests/test_tools.py::test_luacheck_tool_lints_the_file_closure
  - tests/test_tools.py::test_luacheck_globals_exist_in_the_runtime
verified: flua 0.1.171
---

# The luacheck tool — a linter over the QA's file closure

`flua --tool luacheck main.lua` runs the luacheck CLI over every file
that makes up the QA — main + `--%%file` extras + `--%%include`
defaults, with `$lib` bundled libs resolved (the pack pipeline's
closure) — so an agent never hand-resolves the file set.

The two things the tool adds over raw luacheck:

- **The globals whitelist** — flua/HC3 globals (`fibaro`, `api`,
  `net`, `mqtt`, `json`, `QuickApp`, timers, `RefreshStateSubscriber`,
  `class`, …) are declared, so the output flags *real* undefined
  variables (the `PCALL` class of bug the HASS round found) instead of
  expected-global noise. The whitelist is pinned: every name must
  still exist in the Lua runtime or the test fails.
- **The closure** — one command covers the whole QA, with
  `allow_defined` so a global *assigned in any closure file* is legal
  everywhere (multi-file project state like a shared `HASS` table
  stays quiet) and `class 'Name'` declarations recognized as globals.
  A project `.luacheckrc` next to the main file (or in the cwd)
  **fully replaces** the generated config — per-project style is the
  project's call, and the project must then include the runtime
  globals it uses. Bundled-lib basenames (qwikchild, eventlib, ...)
  get their style classes (212/3xx/4xx/5xx/6xx) suppressed — flua's
  code, not the QA author's — while undefined-variable/field (21x)
  stays active.

luacheck itself is **not bundled** — Lua linters ship platform-specific
parsers, so it stays a user install (`luarocks install luacheck` /
`brew install luacheck`); the tool errors cleanly when it is missing.
The undefined-global static pass is the `rainy_day_todos.md` item this
tool defers to the ecosystem for.
