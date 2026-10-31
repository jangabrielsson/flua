# Response to "Experience using flua to test and debug Fibaro QuickApps"

Reply to the GPTAstra feedback report (`GPTAstra_using_flua.md`),
addressed to its author. The report was reviewed against the current tree;
release at the time of this response: **0.1.112** (the report's pilot ran
0.1.84, its installed baseline 0.1.104, with 0.1.111 spot-checks — the
version trail mattered a lot, as you suspected).

Thank you for the report — the evidence discipline (versioned results,
source hashes, adapters disclosed, "not rerun" and "not verified"
qualifications) is exactly what makes this actionable. Several findings
turned out to be already fixed, one turned out to be a real contract bug
we could verify against a live HC3, and the rest are filed.

## Already fixed before this report (0.1.84 → current)

- **Finding 6, instant-mode "bunched callbacks and ordering failures"** —
  fixed in 0.1.111: instant mode is now deadline-ordered (the same
  discipline as `--step`); each callback observes its own deadline. The
  symptom you recorded on 0.1.84/0.1.104 cannot happen anymore. The
  stale "instant is unsafe" caveat was also removed from USAGE.md and the
  migration skill.
- **Finding 7, full-template restart "lost reference"** — your failure was
  on 0.1.84; the updateView aliasing / `lost reference` bug was fixed in
  0.1.87 and is pinned by `test_update_view_alias_regression`. Very likely
  closed. **Please rerun your preserved full-template reproduction on
  0.1.112** — that is the one check only you can do, and if it still
  fails we want the reduced repro.
- **Finding 8, assertion counts alone are not a verdict** — largely
  covered by 0.1.112: `--strict-tests` makes unhandled callback errors
  sticky (exit 1 even if a later callback exits 0) and `--result-json`
  writes a normalized final record (`passed`/`failed`/`timeout`, exit
  code, runtime, clock mode, wall/virtual seconds, failures with kinds).
  What remains (the `runtime_error`/`incomplete` distinction and an
  explicit suite-completed marker) is filed below.
- **Finding 13, `--%%svar`** — shipped in 0.1.110. Your semantic notes are
  accurate and match the implementation: svar wins over a same-named var,
  blank package values (`,""`) are the distribution-safe spelling, and the
  directive masks the editor but does not encrypt. The docs-prominence ask
  is filed below.
- **Finding 4, PLua include paths** — mostly fixed since your versions:
  `--%%include`/`--%%file` anchor to the declaring file, the legacy
  `--%%file:path:name` spelling gets an explicit migration hint in
  `--check` and `--tool migrate`, and the migrate tool scans projects for
  plua leftovers. The remaining ask (a diagnostic naming declared/base/
  resolved paths) is filed as a small follow-up.

## Changed in response to the report

### Finding 5 — property endpoint contract (verified against a live HC3, fixed)

You were right, and the sim was wrong. A read-only capture against a real
controller (recorded in `docs/feedback/hc3_property_endpoint_capture.md`)
confirmed:

| Case | Status | Body |
|---|---|---|
| boolean `false` | 200 | `{"value": false, "modified": 1793263194}` |
| zero | 200 | `{"value": 0, "modified": 1793263194}` |
| empty string | 200 | `{"value": "", "modified": 1793263194}` |
| object | 200 | `{"value": {}, "modified": 1793263194}` |
| missing property | 404 | `null` |

flua's `GET /devices/{id}/properties/{name}` now returns the same envelope
for scalars, objects and the computed sun times, 404/null for missing
properties, with `modified` tracked per device (initialized at
registration/first read, advanced on every property change). The contract
is pinned by `tests/test_api.py::test_device_property_get`. **Your
template's scalar-response adapter is no longer needed** — the QA-side
`{value=...}` validation it wrapped around should now pass unmodified
against the sim.

### Finding 9 — documentation/skill inconsistencies (all fixed)

Verified against the current tree and corrected, plus one more found while
checking:

- `quickapp-dev.instructions.md` — mode example now says offline is the default
- `flua-setup` skill — removed the "online mode is the default"
  contradiction; LuaLS configuration now says Lua 5.4 (matching the
  runtime and the shipped `.luarc.json`)
- `flua-troubleshooting` skill — `.directives` → the current
  `.flua-directives` mechanism; `pip show flua` → `python -m pip show
  fibaro-flua` (correct distribution name)
- `plua-migration` skill — removed the stale "`--instant` is unsafe for
  `os.time()`-relative logic" caveat (0.1.111 invalidated it)

Your point about generated-vs-canonical consistency is taken: these now
match, and the packaged copies are guarded by byte-equality sync tests so
a drift fails CI rather than reaching users.

## Parked (filed in `docs/rainy_day_todos.md`)

- **Finding 8 remainder** — `runtime_error`/`incomplete` outcome values
  and an explicit suite-completed marker in `--result-json`
- **Finding 13 remainder** — `--%%svar` prominence in credential examples
  and a migrate-scan mention (plua parsers ignore svar, so a converted QA
  can drop variables in a plua-packaged flow — your compatibility warning
  is correct)
- **Finding 10** — an integrated "test an existing PLua project without
  rewriting it" workflow skill (recording versions, resolving the
  companion-file graph, disclosed adapters, clock choice, restart as a
  distinct boundary)
- **Finding 11** — the network-isolation guard (offline sim ≠ contained
  network): filed as a simplified `--network-policy deny|loopback`, with
  the full allowlist/DNS/redirect machinery explicitly rejected
- **Finding 12** — an evidence-packaging checklist (versions, hashes,
  clock settings, adapters, verdict, trace locations, redaction)
- **Finding 4 remainder** — the richer include diagnostic

## Your priority list, one line each

- **High — property endpoint (5):** done, live-capture-verified.
- **High — run outcomes (8):** mostly done in 0.1.112; the enum refinement
  is parked.
- **High — consistent guidance (6 and 9):** 6 was a bug (fixed 0.1.111);
  9's four inconsistencies are fixed.
- **Next — harness recipe (4 and 10):** 4 mostly done; 10 parked.
- **Next — credentials (13):** shipped 0.1.110; docs prominence parked.
- **Investigate — restart case (7):** likely fixed by 0.1.87; a rerun on
  0.1.112 on your preserved template is the decisive test, and we'd be
  glad for the result either way.

Please rerun your template suite on 0.1.112 — in particular without the
scalar-response adapter — and the full-template restart. Any new findings
get the same triage.

— flua maintainers
