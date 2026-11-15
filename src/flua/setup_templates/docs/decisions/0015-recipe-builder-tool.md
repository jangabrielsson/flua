# 0015 — the recipe builder is a tool on top of flua, parked as a PoC

- **Status:** active
- **Date:** 2026-11-15

## Context

ADR 0013 pinned the wizard-shaped temptation away: no no-code assembly
surface, because coding agents were absorbing exactly that audience. The
builder (`flua --tool build`) is a multiple-choice recipe assembler — on
its face, the thing 0013 said needs an ADR change to exist. Two premises
from 0013 have not held so far, and the feedback loop has not closed:

- The agent audience has not arrived at the predicted rate — forum
  uptake is still the hard-core ex-plua crowd; many users do not have
  (or will not pay for) an agent, so the agent loop cannot serve them
  today.
- Recipes and verify scenarios turned out to be agent-shaped artifacts
  (plain Lua plus a manifest JSON; `--list`/`--verify` with `--json`),
  so the builder feeds the agent loop instead of competing with it.

The builder is therefore shipped as a **proof of concept, parked** until
user feedback says whether it earns its place.

## Decision

The builder exists as an engine-first tool under 0013's own discipline,
not as a second implementation:

- `flua --tool build` — the CLI is the product surface; the page is a
  thin face over the same endpoints, and every channel has a `--json`
  form for agents.
- Recipes are repo artifacts: `recipes/<id>/{main.lua,manifest.json}`,
  fetched live (one merge, no release), with declarative verify
  scenarios that run in the sim (`--verify`/`--verify-all`, CI-gated on
  template paths). The generated artifact is ordinary Lua the user owns
  and edits — no block editor, no expression ceiling beyond Lua itself.
- 0013's verification-legibility direction is the same surface: the
  scenario steps render as PASS/FAIL lines a non-coder can judge.
- 0013's core stands: the agent environment remains the moat and the
  primary investment; the builder is not a parallel app to maintain.

## Consequences

- ADR 0013 is amended: the "no no-code assembly surface" rule gains a
  delimited exception — a recipe-based builder tool, parked, with the
  first user feedback deciding whether it stays.
- If the feedback is negative, the builder shrinks to the CLI
  (`--list`/`--verify`); the recipes themselves stay valuable as agent
  examples either way.
- The page must not grow into a wizard: any capability it gains must
  arrive as a `--tool build` CLI/JSON surface first.
