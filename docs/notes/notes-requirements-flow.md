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
mechanical.

## The state machine: two loops, two human gates

The whole process is one state machine, driven by a single initial
prompt — the **brief** — that tells the agent how to interact with flua
through every state until "done":

```
                 LOOP 1 — requirements (user ⇄ agent ⇄ flua)
                 user speaks in natural language; the agent
                 formalizes it into the spec (rendered, diffed);
                 repeat until the user APPROVES the spec
                              │ spec approved
                 ┌────────────▼────────────┐
                 │ LOOP 2 — implementation  │
                 │ (agent ⇄ flua testbed)   │
                 │ write → run → R1..Rn    │
                 │ PASS/FAIL → fix, until  │
                 │ every check passes      │
                 └────────────┬────────────┘
                              │ all checks pass
                 ┌────────────▼────────────┐
                 │ 3. "is this ok?" — the  │
                 │    demo gate            │
                 └────────────┬────────────┘
                 "not quite"  │    "yes"
   (back to loop 1 with the   │
    correction, as a spec     ▼
    diff)                  4b. done — the user
                            approves; the agent
                            never deploys
```

Three things fall out of this shape:

- **Two human gates, one mechanical loop.** The user approves the *spec*
  (words) at the end of loop 1 and the *behavior* (the demo) at step 3.
  Between them, loop 2 is fully mechanical and agent-owned. The user is
  in control exactly twice — the two places judgment cannot be delegated.
- **The spec is the only artifact that crosses a loop boundary.** Loop 1
  produces it; loop 2 consumes it (checks derive from requirements); a
  "not quite" at the demo gate re-enters loop 1 as a *spec change* (a
  visible diff), and loop 2 re-runs from the updated spec. Code never
  travels back — it is disposable; requirements are not.
- **The initial prompt IS the state machine.** One brief encodes: iterate
  loop 1 until the user approves; run loop 2 until every requirement
  check passes; ask at the gate; route 4a/4b. That is exactly what
  `--tool spec prompt` renders.

## Loop 1 is analysis, not transcription

The two loops are not equal in importance. Loop 2 is becoming commodity
— agents implement against a testbed in their own ways, and flua already
makes that mechanical. Loop 1 is where the value is, because the two
participants have wildly different budgets: **the agent can run a
thousand analysis iterations, the user can answer a handful of
questions.** A requirements tool that makes the user do the agent's work
is a typing monkey; the whole point of treating the requirement as a
first-class artifact is that the agent can think about it *before*
anything runs.

The loop-1 protocol therefore gains an analyze-before-ask phase, on
every user utterance:

1. **Formalize** — translate the user's words into spec edits (the
   rendered diff, as before).
2. **Analyze** — work the spec as an artifact, not as prose. A
   requirement-analysis checklist (a template-library entry, agent-side)
   enumerates the question classes:
   - *trigger completeness* — what starts it, what stops it, what
     re-arms it (R3's "manual off wins" ambiguity);
   - *timing and failure edges* — DST, controller/QA restart (state is
     lost!), device offline, sunset data missing, power loss;
   - *scope and identity* — which of the matching devices, which rooms,
     which exceptions ("but not if the alarm is armed");
   - *interactions* — other QAs and scenes touching the same devices;
     the house has actors the spec does not know yet;
   - *contradictions* — two requirements that cannot both hold (R2 vs
     R3 shapes), detected by reasoning;
3. **Ask — minimally.** Only the questions that survive the analysis
   pass reach the user, ordered by value, few per turn. The budget rule
   is explicit in the protocol: the user's answers are the scarce
   resource; every question must be one the agent could not settle
   itself.

**The division of labor: flua checks facts, the agent checks
thinking.** flua's loop-1 surface is a **fact-checker**, not an oracle of
requirement quality: `--tool spec check` validates the spec against
reality, with no implementation run and no opinions about what makes a
requirement good:

- *existence and identity* — every named device/room resolves against
  the hub (the house ground truth), and the name matches a unique
  device ("3 matches for 'hall light' — which one?");
- *type and capability* — the referenced device type is real, and the
  intended actions fit its capabilities (a binarySwitch has no
  `setValue` 0–99; the catalog knows the canonical actions);
- *vocabulary validity* — cron tuples are well-formed, sunrise/sunset
  offsets in range, global variables referenced exist (or are flagged
  to be created);
- *environment facts* — the location is set (sunset math needs it),
  the referenced globals/scenes exist.

Everything else — trigger completeness, timing and failure edges,
contradictions, interactions, whether a check verifies the transition —
is **agent-side analysis**. The agent runs its reasoning; flua answers
the questions of fact it can answer a thousand times for free. The user
only sees what survives both.

The resulting division of labor: **the agent explores the requirement
space; the user decides.** The spec is where the exploration is
recorded, so the user can review *thinking*, not just conclusions — a
decision the user accepts is one line; a question the user asked the
agent to settle is a diff.

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

## The requirements editor

The user edits the spec by *dialogue*, not by editing files. Shape: two
panes in one surface.

- **Top**: the requirements as the agent currently interprets them — the
  rendered spec, requirement ids visible, changes highlighted as they
  land (the diff IS the feedback). This pane is the ground truth; the
  user reads it and corrects it.
- **Bottom**: a chat field — the user specifies requirements in natural
  language ("no, the hall light, not the kitchen — and only after dark").

Each chat turn flows through the **interpreter**, which turns prose into
spec edits: the top pane updates, the user sees their words reflected
(or mis-reflected — which is the point: the interpretation is visible and
correctable, not hidden).

**Who asks the questions: the agent, via MCP Tasks.** The interview is
agent-driven work — the *agent* asks the user questions and translates
the answers into spec edits, and the user answers in the chat UI they
already have. flua's role shrinks to the part only flua can do: hold the
spec state, validate edits, and render it. Two mechanisms, primary and
fallback:

1. **MCP Tasks (`io.modelcontextprotocol/tasks`, the official way)** —
   the spec becomes a long-running task: the agent starts it, drives the
   dialogue through the task's input request, writes spec edits through
   its update tool, and flua validates + persists + renders each state.
   The capability is announced in the session capability exchange, so
   agents discover the task surface. **flua holds no LLM keys** — the
   user's own agent account does the interpretation; flua never asks for
   access tokens. Exact tool shapes are pinned against the Tasks
   extension spec when implemented, not here.
2. **Job-id / polling (the manual, backward-compatible way)** —
   `spec/start` returns a `specId`, `spec/update`/`spec/state` carry the
   conversation and a `spec/stop` closes it. This is precisely the
   pattern flua-mcp's session tier already proves (`qa_start` →
   `{sessionId, qaIds}`, `qa_probe`, `qa_action`, TTL reaping,
   transport-stateless) — the spec task reuses the same machinery.

The trust argument settles the earlier interpreter question: with Tasks
(or the fallback), the interpreter is **always the user's agent**, never
flua — no LLM endpoint config, no `.env` keys, no dependency. The direct
LLM backend (open question 12) is dropped unless a standalone editor
without any agent ever materializes.

**The two panes become two windows.** The interaction model is still
"requirements on top, chat below" — but the chat pane is the user's
agent UI, and the top pane is flua's rendered spec (the checklist page
under `--ui`, or the terminal render). The cost: no single integrated
surface. The gain: nothing new to build for the chat half, and the
rendered spec is the same artifact the demo gate reviews. A later TUI or
a spec page with a chat box is an optional integration, not v1.

Launcher discipline unchanged: `--tool spec ...` first (ask/prompt/report
+ the task/session tools), apps on top.

## The sub-agent framing

This is the current trend made concrete: the spec/prompt is the **brief
for a specialized QA sub-agent**. The user's everyday agent is the
parent — it interviews the user, hands the QA sub-agent the brief, and
shows the user the results. The sub-agent's entire world is:

- the **requirements** (with ids — the acceptance vocabulary);
- the **tool inventory** — what flua/flua-mcp expose: `qa_check`,
  `qa_run`, `qa_test`, `--tool house` (ground truth), `--tool newQA`
  (device templates), the sim with its bundled sim devices;
- the **knowledge artifacts** — the skills as `flua://skills/*`
  (best-practice code, patterns, write-safety), served resources;
- the **loop protocol** below — including when to come back to the user.

flua's role in this framing is not to write code but to be the best
possible *environment* a sub-agent can be dropped into — ADR 0013's moat
thesis, stated as architecture. The brief makes the sub-agent
specialized; the environment makes it succeed.

## The house in the spec = the emulator setup

Part of requirements collection is the user's **home environment** —
rooms, devices, their types. In the spec this section does double duty:

- it is the **symbolic reference** the code compiles against
  (`HT.hall.motion`);
- it **compiles to the emulator seed** — a seed file (`--seed`/`--%%db`)
  that stands up the simulated house with the right devices (types,
  names, rooms; the bundled sim devices and `newQA` templates cover the
  catalog). The testbed then mirrors the user's house *shape*, so the
  sub-agent tests against the user's world, not an abstract one.

When the user has a real HC3, `--tool house` provides the ground truth
instead of interview answers — the house section is fetched, not guessed.
The interview's "which rooms, which devices" questions only fire when
that is not available.

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
  - *demonstrate* — when the checks pass, the sub-agent stands up the
    simulation (seeded house + the QA running, timeline/UI in the
    viewer) and asks the user **"is this how you want it?"** — the
    running sim is the prototype the user reviews, not the code;
  - *finish* — the user confirms the demonstration; the agent never
    deploys (flua's standing rule, restated).
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

CLI-first throughout (`--tool spec ask|prompt|check|report`), so agents get the
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
   (The requirements editor above is the intended answer — dialogue, not
   a form.)
7. **Scene specs** — in or out of v1? (Leaning out; QA-shaped first.)
8. **Sharing specs** — a community spec library is the eventual network
   effect; not v1.
9. **House collection channel** — real HC3 ground truth via `--tool
   house`, an interview-built seed, or both (fetch when reachable, ask
   when not)? And who compiles the seed — the spec tool or the sub-agent
   itself from the spec's house section?
10. **The "is this ok?" demo surface** — where does the user review the
    prototype: the `--ui` viewer/timeline (interactive), the rendered
    checklist, or both? The answer decides whether the viewer grows a
    "confirm/refine" affordance.
11. **Editor form factor** — v1: no chat surface at all (the agent UI is
    the chat; flua renders the spec). Does the terminal `--tool spec`
    render suffice, or does the `--ui` viewer get the spec page early so
    the demo gate and the spec share a surface?
12. **Interpreter backend** — resolved by Tasks: the user's agent, never
    flua. Open: pin the exact Tasks tool shapes against the extension
    spec; decide whether the job-id/polling fallback reuses the session
    tier machinery directly (leaning: yes).
13. **The analysis checklist** — an agent-side template entry (skill),
    with the fact checks above as the flua-side `spec check` surface.
    Which facts are checkable keeps growing as the house ground truth
    and the device catalog deepen — the linter's scope is whatever flua
    can answer *about the world*, never about requirement quality.

## First slice (the vertical proof)

`--tool spec ask --from-template motion-light` against a `--tool house`
snapshot → emit the spec markdown and `--tool spec prompt` renders the
driving brief (spec + house refs + loop protocol) → hand it to an agent
(Copilot/Claude/MCP) that loops in the sim → `--tool spec report` renders
the checklist from the last `flua test` run. One template, end to end,
proves the loop — with flua generating zero code.
