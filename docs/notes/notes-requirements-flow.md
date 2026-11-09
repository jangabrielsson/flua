# Note: the requirements flow — elicitation and verification on the agent loop (design draft)

Status: design draft — nothing implemented (2026-11-09). ADR 0013 is the
mandate; this note is the shape exploration.

## Context and goal

ADR 0013 committed flua to two surfaces instead of a wizard: **requirements
elicitation** (spec + skeleton + test scaffold, CLI-first) and
**verification legibility** (requirements → PASS/FAIL, judgeable by
non-coders). This note explores what those are, and picks directions.

The core idea in one sentence: **make the requirement a first-class,
versioned artifact that everything downstream compiles from.** The forum
post said "the requirement is the product; the code is just how it
compiles" — this is that made mechanical:

```
elicit ──▶ spec ──▶ code + test scaffold ──▶ run (flua test) ──▶ checklist ──▶ refine
  ▲                                                                        │
  └────────────────────────── the user's loop ◀─────────────────────────────┘
```

The user edits the *spec*, never the generated code. The agent (or the
template engine) recompiles. The checklist renders from the spec, so the
user judges in their own words. That closed loop is the innovative part —
the pieces all exist separately; nobody owns the loop.

## Existing pieces this builds on

- `--tool newQA` — device-*type* templates (30 types) with substitution:
  the proven "template + slots" mechanism, but for device shape, not
  behavior.
- `--tool house` — ground truth: devices with id/name/type/room, globals,
  scenes, customEvents. Elicitation can be *concrete*: real rooms, real
  devices, not abstractions.
- `--tool setup` — project scaffold; the spec compilation extends it.
- `flua test` + `flua-test` — self-asserting runs with exit codes; the
  verification half already exists, it just doesn't speak requirements.
- The skills — quickapp-patterns (homeTable, sunset, schedulers),
  hc3-write-safety, scenes: the knowledge the interview and the templates
  draw on, already agent-readable.
- The viewer (`--ui`, timeline, HTML) — where a rendered checklist can
  live without building a new app.

## Shape exploration (the idea space)

**1. Natural-language chat.** Keep it as the *input channel* — agents
already interview users in prose. But prose is a terrible artifact: not
diffable, not compilable, not checkable. Chat feeds the spec; it is not
the spec.

**2. Guided interview (wizard-lite, multiple choice).** The good half of
the wizard: rooms → devices → trigger → conditions → actions →
exceptions, with the choices pulled from `--tool house` (real names, real
types) and the trigger vocabulary from the skills (device change, cron,
sunrise/sunset, global variable, custom event). The difference from a
wizard: its output is a **spec**, not code. Deterministic, testable,
CLI-first (`flua --tool spec ask`). Works for the standard 80% of
automations.

**3. Visual flow diagram (Node-RED style).** Rejected as an *editor* —
ADR 0013's discipline, and agents read text, not boxes. A diagram is at
most a *render* of the spec later (mermaid already renders our forum
diagrams; a spec → flowchart render is cheap and optional).

**4. Solution requirement template library.** The strongest entry point
for non-coders: pick a known-good *behavior* pattern ("motion turns on a
light for N minutes, only after dark", "notify when a door opens and
nobody's home", "thermostat follows a daily schedule") and substitute the
house specifics (which sensor, which light, which times). Distinct from
`newQA`'s device-type templates: this is *behavior*, and it seeds from
quickapp-patterns + the examples. This is also how humans already learn
home automation — by copying a neighbor's automation and swapping names.

**Recommended shape: template library + guided interview → structured
spec.** The template gets the user 80% there by substitution; the
interview fills the gaps with grounded choices; the spec is what
everything compiles from. Natural language stays the agent-side channel.

## The spec (sketch)

A structured, diffable, agent-readable, renderable document. Direction:
markdown with YAML frontmatter (human- and agent-readable in one file —
`json.decode`-friendly where needed), something like:

```markdown
---
name: Hall light on motion
template: motion-light
house: HT                          # symbolic refs only — never baked ids
devices:
  sensor: HT.hall.motion
  light: HT.hall.light
requirements:
  - id: R1
    text: motion after sunset turns the hall light on
  - id: R2
    text: the light turns off after 5 minutes with no motion
  - id: R3
    text: manual switch off during the 5 minutes wins
---
```

- **Symbolic house refs** (`HT.hall.motion`) — the homeTable idiom (ADR
  of ids: names in code, ids behind them). The interview resolves the
  user's words through `--tool house`; the spec keeps names.
- **Requirements carry ids** — the checklist and the test scaffold map
  1:1 onto them. Refinement is visible as a spec diff ("R2 changed from
  10 to 5 minutes").
- **Safety defaults ride along** — write-safety notes (which controller,
  read-modify-write) as spec fields, so the generated code inherits them.
- **Scenes caveat** — a spec whose trigger is a scene must carry literal
  ids (triggers can't use variables); the spec model should say so
  explicitly rather than pretend.

## Compilation: spec → skeleton + tests + checklist

- **Skeleton**: `--tool setup`-style project from the template with the
  spec's slots filled (names, devices, times) — or, for the non-template
  long tail, a spec-aware prompt emitted for the agent (the spec *is* the
  prompt; the agent fills the rest).
- **Test scaffold**: one self-asserting check per requirement, phrased in
  the requirement's words: `R1: motion after sunset turns the hall light
  on — PASS`. Generated from the spec's `requirements`, run by `flua
  test`, verified in the sim (virtual clock tests the sunset case).
- **Checklist render**: `--tool spec render` → HTML/MD of the spec with
  each requirement's last verdict — the judgment surface. A non-coder
  reads "R2: PASS" and knows what to say next; they never read Lua.

## Form factor

CLI-first throughout (`--tool spec new|ask|render|verify`), so agents get
the identical surface via `flua_tool`/MCP — the app discipline from ADR
0013. A thin web form for the interview can come later under the existing
`--ui` server; it must emit the same spec format.

## What this is NOT

Not a visual editor. Not a full code-generation platform — the agent
handles the long tail; templates cover the standard patterns. Not a
block-scene clone — the HC3's block editor owns that; our specs that
compile to scenes do so deliberately (literal-id caveat).

## Open questions (the iteration surface)

1. **Spec schema** — markdown+YAML frontmatter vs pure YAML/JSON with a
   markdown render? The former reads better to humans; the latter is
   easier to validate. Leaning frontmatter.
2. **How much codegen?** Templates fill slots; the agent writes the long
   tail. Where's the line? Start with "skeleton + filled template, agent
   does the rest" and let the template library grow.
3. **Spec↔code drift** — what happens when a user or agent edits the
   generated code directly (the normal programmer path)? Options: spec
   owns requirements and code is disposable; or a `spec sync` that
   back-annotates. This is the hardest design question.
4. **Template library home** — skills tree (agent-installable, already
   synced) vs a new `setup_templates/specs` dir vs both (source in one,
   sync to the other)?
5. **Interview UX** — terminal Q&A first, web form later? How many
   questions before it feels like a wizard again (the thing we rejected)?
6. **Scene specs** — in or out of v1? (Leaning out; QA-shaped first.)
7. **Sharing specs** — a community spec library is the eventual network
   effect; not v1.

## First slice (the vertical proof)

`--tool spec ask --from-template motion-light` against a `--tool house`
snapshot: emit the spec markdown, the project skeleton with filled slots,
and the test scaffold; run it under `flua test` in the sim; render the
checklist. One template, end to end, proves the loop. Everything else
grows from there.
