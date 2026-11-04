# HC3 parity harness — design

Verifying that flua behaves like the HC3, quirks and all, against a real
controller. Planned (2026-11-04); the FluaHelper is the Tier-3 transport.

## Cadence shapes the architecture

The harness runs rarely — every Fibaro FW release (and whenever a flua
version claims new surface). So the controller must only be needed at
*capture* time; everything after that is offline. Two artifacts:

- **capture** — against the real HC3, produces checked-in fixtures;
- **replay** — offline, deterministic, in CI forever, diffs the sim vs
  the fixtures.

Firmware upgrades become: `parityCapture` → review the printed delta →
commit fixtures + any sim fixes.

## Layout

```
src/flua/parity/
  normalize.py     # shape+id normalization, drift diff (extracted from
                   # test_hc3_compat.py's _shape/_drift — compat reuses it)
  probes.py        # probe list: every implemented GET derived from the
                   # route registry (ROUTES), concrete sim paths + live
                   # resolvers + house filters
  mutations.py     # Tier-2 sequences (customEvents, globalVariables,
                   # QA lifecycle) + the artifact tracker (LIFO teardown)
src/flua/tools/parity_capture.py  # flua --tool parityCapture (registry
                   # convention: one module per tool; --mutations adds the
                   # Tier-2 sequences)
src/flua/tools/parity_cleanup.py  # flua --tool parityCleanup — removes
                   # flua-p-* leftovers from crashed captures
tests/hc3_parity/
  probe_qa/
    main.lua       # in-QA self-test, runs identically on HC3 and in sim
                   # (built on dev/apitest.lua; a test fixture, so it lives
                   # here, not in src/)
  fixtures/<softVersion>/           # transcripts, checked in
    meta.json      # serial, softVersion, flua version, helper version, date
    shapes.json    # GET shape probes (status + normalized shape)
    mutations.json # CRUD sequences (status + shape + id placeholders)
    fibaro.json    # helperFibaro results (types + error semantics)
  test_hc3_replay.py   # offline replay suite, CI forever
```

Capture and replay are checkout-based activities anyway (the fixtures are
checked in next to the suite), so test material lives under tests/; only
the capture tooling itself is product code in src/.

## The four layers

### 1. Shape probes (read-only, zero risk)

Auto-derive from `routes/__init__.py`'s `ROUTES` table — the route registry
is the single source of truth for what the sim implements; the
`--capabilities-json` table stays the honesty surface, not the driver.
Every implemented GET becomes a probe: `{method, path with concrete ids,
params, house-normalizer}`. House-normalizers are mandatory (filter device
lists by type, drop serial/hcName, replace ids with `<id>` placeholders) —
the HC3 under test is a real house, values are not comparable.

Capture records status + normalized shape per probe; replay runs the same
probe against the sim and reuses the existing problems-vs-gaps drift:
problems fail (sim bug), gaps report (unmodeled fields — the sim is a
subset).

### 2. Mutation probes (controlled, guaranteed cleanup)

A session-scoped artifact tracker: every probe creates only
`flua-p-<uuid8>`-prefixed artifacts (QA, customEvent, globalVariable),
registers them, and teardown deletes LIFO; `--tool parityCleanup` removes
orphans from crashed captures. Settings PUTs snapshot and restore the old
value (hcName!). Covers QA create/upload/call/updateProperty/delete,
customEvents CRUD + publish, globalVariables add/change/delete.

Capture runs the sequence against the real HC3 and pins status + shape +
id placeholders. Replay executes the *same sequence* against the sim
(deterministic — seed house, no controller) and compares. This is what
makes Tier 2 CI-able instead of HC3-gated. (Decided: the trade-off —
capture pins are still real HC3 responses, only the replay execution is
offline.)

### 3. QA runtime probes (what QAs *observe*)

Two directions, both enabled by the helper:

- **In-QA self-test**: the probe QA (built on `dev/apitest.lua`, promoted
to `tests/hc3_parity/probe_qa/`) is uploaded to the HC3 via the existing
REST import and
  exercises api calls, updateProperty/updateView quirks, timers, emitted
  events — logging everything to `/debugMessages`. flua's
  `/debugMessages` is real, so the *same* QA runs in the sim and the
  harness diffs the two debug transcripts (normalized). Verifies the
  runtime as observed from inside a QA, not the REST response.
- **fibaro probes**: for each `fibaro.*` entry in the capabilities table,
  `api.helperFibaro(name, args)` runs it controller-side in the helper's
  context. Capture pins return types and error semantics (nil-function
  behavior, bad-arg errors). Replay compares the sim's `fibaro.*` on the
  same house-independent args. The helper is exactly the Tier-3 transport
  the parked note was missing.

### 4. Quirk pinning

Every HC3 quirk discovered (updateView string values, selectedItem
matching, 404-vs-400 behaviors, id reuse, restart semantics) becomes one
behavioral test with the expectation captured from the real controller.

## FW release workflow

1. User upgrades the HC3 FW (their cadence, not ours).
2. `HC3_TEST=1 flua --tool parityCapture --fw 5.221` → writes
   `tests/hc3_parity/fixtures/5.221/`, prints the diff vs the previous
   fixture.
3. Review the delta, three verdicts: flua bug → fix the sim; real HC3
   change → update sim + fixture; house noise → extend normalization.
4. Commit fixtures + fixes; the replay suite keeps it pinned in CI.

Replay defaults to the newest fixture; `--fw` pins an older one. Fixtures
are keyed by softVersion only (decided).

## Safety rails

Namespaced artifacts only (`flua-p-*`); never touch existing
devices/globals; settings PUTs restore their old values; dry-run listing
before capture; the existing auth-lockout guard stays. The existing
opt-in live suites (`test_hc3_live.py`, `test_hc3_compat.py`) keep their
role as quick smoke checks; capture is the new deep entry point.

## Implementation order

1. ~~Extract the shape oracle~~ — done: `flua.parity.normalize`
   (`shape`/`drift`), compat suite reuses it.
2. ~~Capture tool + fixtures + replay suite~~ — done: `--tool parityCapture`
   (read-only, `--dry-run`, `--fw`, `--fixtures`), fixtures keyed by
   softVersion, `tests/hc3_parity/test_hc3_replay.py` replays offline
   (`--parity-fw` pins one fixture; without fixtures it skips; the
   comparison machinery is pinned by a synthetic-transcript test and the
   probe coverage by a route-registry test). First milestone complete:
   whole GET surface captured and replayed.
3. ~~Mutation probes + artifact tracker + `parityCleanup`~~ — done:
   customEvents CRUD+fire+publish, globalVariables add/change/read/delete
   (pins the post-delete 404), QA lifecycle (create/read/updateProperty/
   read property/delete — no Lua needed on either side; the HC3 .fqa vs
   sim {name} body asymmetry is modeled as an explicit per-side body).
   `--mutations` gates the capture-side sequences; teardown is LIFO via
   the tracker; `--tool parityCleanup` lists/deletes flua-p-* leftovers
   (prefix-guarded). Replay runs the same sequences against an
   engine-backed sim and compares status + shape per step.
   Deferred: the settings PUT snapshot/restore probe — it changes real
   controller state and deserves its own deliberate run, not a default.
4. Probe QA (debugMessages transcript diff) + helperFibaro probes.
5. Quirk pinning as discoveries surface during capture runs.
