# 0013 — no wizard app; the agent loop is the product surface

- **Status:** active
- **Date:** 2026-11-09

## Context

A recurring temptation: a drag-and-drop / multiple-choice "wizard" app on
top of flua that helps non-coders assemble QAs. It feels generous — and it
misses the moment. Coding agents are absorbing exactly that audience:
roughly half the forum already has an agent writing their QAs, and the
curve points at everyone. A wizard competes with an unbounded, free
engineer using a fixed expression ceiling (every block is a capability
someone must pre-build, and the union of blocks is always less than Lua).

The thesis we already publish says it directly: *the requirement is the
product; the code is just how it compiles.* A drag-drop app re-makes the
code the product. The repo's engine-first discipline
(`docs/notes/notes-vscode-hub-browser.md`) already states the shape of any
correct app: flua is the engine — for agent-loop development and for
programmers; GUI conveniences are apps on top, and nothing may exist only
in an app. For scene-style automations the HC3's own block editor is
already the wizard; flua's role there is convert → test → understand.

What non-coders actually lack is not syntax but **articulation** (they
don't know to say "sunset", "re-inclusion changes ids") and **judgment**
(they can't delegate "did it do what I wanted?"). Those two are the real
product gaps, and they are much cheaper than a wizard.

## Decision

**No drag-and-drop wizard app.** Instead, two thin surfaces that feed the
agent loop, and a standing investment priority:

- **Requirements elicitation, not code generation.** When built, an
  interactive flow (rooms → devices → trigger → actions → exceptions)
  that emits a *spec* for the agent plus a flua project skeleton with a
  self-asserting test scaffold. Its job is a better prompt, not code. It
  must be CLI-first (`--tool`), so agents and CI get the same surface as
  any future GUI — the existing app discipline applies unchanged.
- **Verification legibility.** The run verdicts rendered as a
  requirements checklist (each requirement → PASS/FAIL from `flua test`),
  so a non-coder can judge the result without reading code. Judgment is
  the one part of the loop the user cannot delegate; make it the most
  legible part.
- **The moat is the agent's environment.** flua's durable claim is being
  the best *environment* for agents: the testbed (safe iteration), ground
  truth (the house as data), guardrails (write-safety, deploy), and the
  guidance surfaces (MCP, skills). Agents are a commodity; environment
  quality is not. Keep investing there.

## Consequences

- Accepted: no no-code assembly surface; users who want one keep the
  HC3's block editor (for scenes) or get better service from an agent
  with flua. The wizard-shaped temptation is pinned here, so it needs an
  ADR change to come back.
- Committed: when elicitation and verification surfaces are built, they
  are engine-first (`--tool`/CLI), testable offline, and their outputs
  (spec, skeleton, checklist) are plain text artifacts an agent can
  consume.
- The extension stays the first app (hub browser, completions, home
  table) under the same discipline; any future GUI is the human face of
  the CLI, never a second implementation.
