# plua → flua migration report — Dirigera project

Date: 2026-10-28 · flua 0.1.98 (Lua 5.4) · checked against the real Dirigera hub
(live HTTP/WebSocket) and the real HC3 (read-only probe).
Companion file: `doc/FLUA_BUG_REPORT.md` (upstream bugs with repros).

---

## 1. What this check covered

The ported code (`Dirigera.lua`, `Lib.lua`, `Devices.lua`, `Auth.lua`), the
release management scripts (`scripts/`), and the packed artifacts
(`Dirigera.fqa`, `dist/Dirigera.fqa`). Method: `flua --check`, offline runs
against the real hub, UI compilation, a fresh `flua --tool pack`, the old
`plua -t pack` path, and a read-only online probe of the HC3.

## 2. Migration status — what works

- **All four Lua files pass `flua --check`** (Dirigera.lua emits 3 warnings,
  see §3.1) and the QA boots cleanly in the emulator.
- **Live integration works offline**: `net.HTTPClient` and
  `net.WebSocketClientTls` really connect in offline mode — the QA pulled
  device/scene/home data from the real hub and opened a live WSS connection.
  Only the HC3 surface is mocked, which matched my expectation for this
  project (confirmed by the owner).
- **UI compiles correctly**: the `--%%u:{{button...},{button...}}` rows
  produce working buttons + callbacks + the device selector in the compiled
  view. (Only `flua --tool ui`'s text output misleads — upstream bug #2.)
- **Everything plua-specific the code uses exists in flua**: `plugin`,
  `__TAG`, `net.WebSocketClientTls`, `json.util.InitArray`, `class`,
  `QwikAppChild`, and the `$sha2.lua` / `$qwikchild.lua` system-file
  references all resolve.
- **`flua --tool pack Dirigera.lua -o dist/Dirigera.fqa -f` works** and
  produces a correct 6-file package (apiVersion 1.3, current variable
  values). The old `plua -t pack` fails on these sources — see §3.2.
- **Secrets**: the hub token resolves through the `.env` chain in the
  emulator exactly as intended.

## 3. What still needs fixing (project side)

### 3.1 Dead plua directives in `Dirigera.lua` (low)

```lua
-- %%save:Dirigera.fqa
-- %%proxy:true
-- %%port=8269
```

Space before `%%` = plua spelling; flua warns and ignores each. They do
nothing now (`--%%mode:offline` already pins the mode, `pack -o` sets the
output). Remove them.

### 3.2 Release scripts still call plua (high for releases)

- `scripts/project-config.sh` ARTIFACTS:
  `plua -t pack {SOURCE} {OUTPUT}` — **fails on the current sources**
  (`Library not found: '$sha2.lua'`; the plua install no longer carries the
  system files). flua equivalent:
  `flua --tool pack {SOURCE} -o {OUTPUT} -f` (needs `-f` to overwrite
  `dist/Dirigera.fqa`).
- `scripts/create-release.sh` `check_dependencies` requires the `plua`
  binary and points users to the plua repo → check `flua` instead.
- `scripts/README.md` and `scripts/project-config.sh.example` still document
  plua as the packer.

Net effect: `./scripts/create-release.sh` would die at the artifact step
today even though the rest of the release flow (setversion, changelog, tag,
gh release) is tool-agnostic and fine.

### 3.3 Stale artifacts (medium)

- `dist/Dirigera.fqa` (Apr 2026) predates the current sources (Apr/Oct
  2026): all 6 embedded files differ, and the baked `IP` var is
  `192.168.1.165` while the source says `192.168.50.165`.
- Root `Dirigera.fqa` (Sep 2025) is an old plua-format package (`"type":"lua"`
  file entries, `"Auth;"` name quirk) — obsolete; consider deleting it or
  replacing it with a flua-packed copy.

### 3.4 Distribution hygiene (low)

`--%%var:IP="192.168.50.165"` bakes the private LAN IP into the distributed
`.fqa`. Use the package-value form
(`--%%var:IP="192.168.50.165","<your-hub-ip>"`) so releases ship a
placeholder while your own HC3 uploads keep the real value.

### 3.5 Online testing needs an extra flag (awareness, not a fix)

Because of upstream bug #1, running this QA against the real HC3 requires
`flua --api remote -D mode:online` — `--api remote` alone silently keeps the
QA's `api.*` calls on the sim.

## 4. Upstream findings (for flua)

Full repros in `doc/FLUA_BUG_REPORT.md`:

1. **High** — `--api remote` does not win over the main QA's
   `--%%mode:offline`: engine runs online but the QA's `api.*` stays on the
   sim, silently (proved with `/settings/info` serials).
2. **Low** — `flua --tool ui` text renderer drops components nested in
   `horizontal`/`vertical` containers (legacy viewLayout path), so
   multi-button rows print as blank "space" lines.
3. **Minor** — `plugin.restart()` does not halt the current turn; code after
   the call runs in flua but not on the HC3.

## 5. Opinion on flua

### What's good

The emulator fidelity surprised me positively. The plua surface I needed
(`plugin`, `__TAG`, `json.util.InitArray`, `net.WebSocketClientTls`,
`$`-system-file resolution, `class`/QwikAppChild) is all there and worked on
the first run. Real network in "offline" mode is the right call for this
kind of hub-integration QA and made the check meaningful. The
`-- %%`-with-space warning in `flua --check` is exactly the right kind of
migration help: loud, specific, per line. The pack tool is clean and the
`.env`/config chain just worked. USAGE.md is a genuinely good manual.

### Missing skills (project's `.github/skills/`)

The skill pack covers setup, API reference, patterns, types, testing and
troubleshooting — but nothing migration-shaped:

- **No `plua-migration` skill.** The single most valuable artifact for this
  exact task: a checklist ("remove `--%%save`/`--%%port`, `-- %%`-space
  spellings, `fibaro.plua` → `_FLUA`, `$system files` now resolve in flua,
  which plua globals are emulated") plus the compat matrix below. AGENTS.md
  has a terse table; a skill with worked examples and the gotchas in §5
  "unclear" would have saved real time.
- **No compat matrix page** anywhere: "plua API → flua equivalent"
  (`--%%conceal` → `--%%clobber`/package value, `--%%desktop` → `--ui`,
  `--%%proxy` → `--%%mode:proxy`, `plugin.restart`, `json.util.*`,
  `net.WebSocketClientTls`, `fibaro.getIPaddress`). I verified each by
  probing the runtime instead of reading a doc.
- The existing `flua-troubleshooting` skill is oriented at runtime
  behavior; a short "migration failures" section (directive warnings,
  pack differences) would fit there.

### Missing features

- **Migration linter**: `flua --check` already flags `-- %%` spellings; a
  `--tool migrate` (or a `--check` severity bump) that lists *all* plua-isms
  in one pass — including `plua -t pack`-style script references, stale
  `dist/` artifacts vs. source timestamps, baked private-IP vars — would
  turn this manual check into a one-liner.
- **`--tool ui` parity**: text and `--json` output should agree (bug #2).
- **Warning on the mode pin**: when `--api remote` meets a main-QA
  `--%%mode:offline`, flua should say so (bug #1) — the silence is the bug.
- Nice-to-have: the banner could say `mode offline (sim HC3, real network)`
  — "offline" reads as "no network", which cost a clarification this
  session.

### Things that were unclear

1. **CLI vs. header precedence for the main QA.** USAGE.md's "an explicit
   `--api local|remote` always wins" did not hold for the QA's own `api.*`
   calls; the per-QA pin is documented only for *secondary* QAs. The
   observed behavior (main QA silently pinned to the sim under
   `--api remote`) contradicts both USAGE.md and this project's own AGENTS.md.
2. **`plugin.restart()` semantics.** USAGE.md says it "re-runs the QA's
   code" — but not that the current turn *keeps executing* after the call,
   which differs from the HC3.
3. **Multi-element `--%%u` rows.** The directive table shows only
   `--%%u:{label=...}` single-element examples; the list-of-dicts row syntax
   `--%%u:{{a},{b}}` is undocumented, and the `--tool ui` text output made
   me think it was broken until I read the compiled view.
4. **"Offline" naming vs. real network** — resolved by the owner, but the
   docs bury it ("real network access" in the intro paragraph) rather than
   stating it next to the mode table.

## 6. Why I went into the flua Python package

The docs stopped answering questions at the exact points where behavior and
documentation disagreed, and the tool output was misleading. Specifically:

- **`flua --tool ui` printed "space" instead of the buttons.** To tell a
  compile bug from a render bug I read `flua/ui.py` (`compile_ui`) — the
  compiled view was correct — and `flua/tools/ui.py`
  (`_render_view_layout`) — which confirmed the renderer only walks one
  level of `components`. The missing information: no doc or tool output
  describes how multi-element rows are compiled or rendered.
- **The `--api remote` / `--%%mode:offline` contradiction.** USAGE.md's
  precedence list said the CLI flag wins; the probe said otherwise. I read
  `flua/cli.py`'s engine-mode resolution and `flua/config.py`'s `_apply_mode`
  to find that the file pin survives at the QA level even when the engine
  backend is remote. The missing information: the two-layer
  (engine backend vs. per-QA pin) model is never spelled out in the docs.
- **`plugin.restart()` continuing execution.** `lua/init.lua`'s
  `restartQA` handler showed the restart is queued for after the turn —
  a detail the USAGE.md summary omits.
- **Which plua globals exist** — answered by `flua -e` probes, because no
  doc page lists the emulated plua surface in one place.

In short: I read the package not because the docs were thin, but because the
docs were confident and wrong (or silent) at precisely the three places the
behavior mattered.

## 7. Recommendations

1. Fix the release scripts (§3.2) and regenerate `dist/Dirigera.fqa` —
   releases are currently broken at the pack step.
2. Clean the dead directives (§3.1) and delete/replace the root `Dirigera.fqa`.
3. Use a package value for the `IP` var (§3.4).
4. Submit `doc/FLUA_BUG_REPORT.md` upstream, with bug #1 first.
5. If upstream accepts fixes: a `plua-migration` skill + compat matrix page
   in this repo's `.github/skills/` would make the next plua project's
   conversion mechanical.
