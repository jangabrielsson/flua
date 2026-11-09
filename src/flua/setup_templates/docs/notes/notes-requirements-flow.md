# Note: the requirements flow — elicitation and verification on the agent loop (design draft)

Status: design draft — nothing implemented (2026-11-09). ADR 0013 is the
mandate; this note is the shape exploration.

## Context and goal

ADR 0013 committed flua to two surfaces instead of a wizard: **requirements
elicitation** (spec + skeleton + test scaffold, CLI-first) and
**verification legibility** (requirements → PASS/FAIL, judgeable by
non-coders). This note explores what those are, and picks directions.

The core idea in one sentence: **make the requirement a first-class,
versioned artifact that compiles to the prompt driving an agent's whole
loop** — build, test in the testbed, verify against the requirements, and
loop back to the user (or the requirements editor) for refinements until
the product is solved. The forum post said "the requirement is the
product; the code is just how it compiles" — this is that made
mechanical:

```
elicit ──▶ spec ──▶ driving prompt ──▶ agent loops in flua (testbed) ──▶ checklist
  ▲            │                          │                                │
  │            │                          └── blocked/ambiguous? ──ask──▶ user
  │            │                                                     │
  └── user refines the spec ◀── requirements editor ◀──────────────────┘
```

The user edits the *spec*, never the code. The spec renders as the
agent's driving prompt; the agent implements and loops against flua's
testbed; when a requirement is ambiguous, contradictory, or missing house
information, the agent stops and asks — with concrete candidates — and the
requirements editor re-opens at the blocking requirement. The checklist
renders from the spec, so the user judges in their own words. That closed
loop is the innovative part — the pieces all exist separately; nobody
owns the loop.

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

## Compilation: spec → driving prompt + check scaffold + checklist

- **The driving prompt** is the primary output. It binds the spec's
  requirements, the house snapshot, and the **loop protocol** into one
  brief the agent executes:
  - *implement* — write the QA against the sim (offline; no controller
    unless mode=remote is explicit);
  - *verify* — run `flua test`/`qa_run`; every requirement maps to a
    check that prints `R<n>: <requirement> — PASS/FAIL`;
  - *fix* — iterate in the testbed until all checks pass; a failed check
    is a bug to fix, not a report to file;
  - *ask, don't guess* — when a requirement is ambiguous, contradictory,
    or the house data lacks the device/room it names, stop and ask the
    user: the requirement id, the concrete question, and the candidates
    from `--tool house`. Bounded retries (e.g. three attempts on one
    requirement, then ask) so the loop never spins silently;
  - *refine* — the user's answer updates the spec (a visible diff), the
    prompt re-renders, the loop resumes;
  - *finish* — all requirements PASS + the user's explicit approval; the
    agent never deploys (flua's standing rule, restated).
- **Check scaffold**: one self-asserting check per requirement, phrased in
  the requirement's words — the starting point the agent implements
  against (the flua-test pattern; the sim's virtual clock tests the
  sunset/schedule cases).
- **Checklist render**: `--tool spec report` → the spec with each
  requirement's latest verdict — the judgment surface. A non-coder reads
  "R2: PASS" and knows what to say next; they never read Lua.
- **Templates** now do double duty: they seed the *requirement set* at
  elicitation time and contribute a reference approach to the *prompt* at
  compile time (a known-good pattern for the agent to start from, not a
  straightjacket).

## Form factor

CLI-first throughout (`--tool spec ask|prompt|report`), so agents get the
identical surface via `flua_tool`/MCP — the app discipline from ADR 0013.
The driving prompt may also ship as an MCP **prompt** (the existing prompt
tier: `qa_spec` taking the spec and rendering the bound brief), so
MCP-only hosts get the loop protocol without installing anything. A thin
web form for the interview/editor can come later under the existing
`--ui` server; it must emit and read the same spec format.

## What this is NOT

Not a visual editor. Not a code-generation platform — **flua generates
zero code**; it elicits the spec, renders the driving prompt, and reports
the verdicts. The agent writes the code; templates give the agent a
reference approach. Not a block-scene clone — the HC3's block editor owns
that; our specs that compile to scenes do so deliberately (literal-id
caveat).

## Open questions (the iteration surface)

1. **Spec schema** — markdown+YAML frontmatter vs pure YAML/JSON with a
   markdown render? The former reads better to humans; the latter is
   easier to validate. Leaning frontmatter.
2. **Protocol home** — the loop protocol in the spec file itself, or a
   stable template (skill/MCP prompt) the spec references? Leaning the
   latter: specs stay clean, the protocol evolves without touching every
   spec.
3. **Spec↔code drift** — the spec owns requirements and the agent writes
   code; what happens when a user or agent edits the generated code
   directly (the normal programmer path)? Requirements stay in the spec;
   code edits are free, but the checklist always re-derives from the
   spec. This is the hardest design question.
4. **Who edits the spec on refinement** — the user, or the agent with
   user approval (the diff as the review surface)?
5. **Template library home** — skills tree (agent-installable, already
   synced) vs a new `setup_templates/specs` dir vs both?
6. **Interview UX** — terminal Q&A first, web form later? How many
   questions before it feels like a wizard again (the thing we rejected)?
7. **Scene specs** — in or out of v1? (Leaning out; QA-shaped first.)
8. **Sharing specs** — a community spec library is the eventual network
   effect; not v1.

## First slice (the vertical proof)

`--tool spec ask --from-template motion-light` against a `--tool house`
snapshot → emit the spec markdown and `--tool spec prompt` renders the
driving brief (spec + house refs + loop protocol) → hand it to an agent
(Copilot/Claude/MCP) that loops in the sim → `--tool spec report` renders
the checklist from the last `flua test` run. One template, end to end,
proves the loop — with flua generating zero code.
