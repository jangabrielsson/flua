# HC3 parity harness — plan

Verifying that flua behaves like the HC3, quirks and all, against a real
controller. Parked as a plan (2026-11-03) until there is a working window.

Existing foundation: `tests/test_hc3_live.py` (opt-in read-only smoke + one
import→call→delete QA round trip) and `tests/test_hc3_compat.py` (the shape
oracle: same call through sim vs live HC3, status + JSON structure).

## Tier 1 — read-only parity, expanded

Auto-derive the probe list from `--capabilities-json`'s `rest` table (every
implemented GET route) and run each through the existing shape oracle.
Zero writes, zero risk. Today the compat suite checks a handful; this makes
it the whole surface.

## Tier 2 — controlled mutations with guaranteed cleanup

A session-scoped artifact tracker: every test creates only
`flua-p-<uuid8>`-prefixed artifacts (QA, customEvent, globalVariable),
registers them, and a teardown fixture deletes them LIFO — plus a
`--tool parity-cleanup` command for leftovers from crashed runs. Covers:
QA create/upload/call/updateProperty/delete, customEvents CRUD+publish,
globalVariables add/change/delete, settings PUT with old-value snapshot +
restore (hcName!).

## Tier 3 — behavioral parity of the QA runtime

Upload a probe QA — the HC3-side twin of `dev/apitest.lua` — that
exercises the surface from inside: api calls, updateProperty/updateView
quirks, timers, emitted events, debugMessages. The harness polls
`/debugMessages` and `/refreshStates` and pins the HC3's actual behavior.
Verifies what QAs *observe*, not just the REST responses.

## Tier 4 — capture-and-replay oracle

Capture mode runs the probe list against the real HC3 and records
transcripts (status + shape + key fields) as checked-in fixtures, versioned
by firmware (`tests/hc3_fixtures/5.221.json`). The replay suite runs the
same probes against the sim, offline, in CI forever, and diffs. The
controller is only needed at capture time; firmware upgrades become
"re-capture → review the delta".

## Tier 5 — quirk pinning

Every HC3 quirk discovered (updateView string values, `selectedItem`
matching, 404-vs-400 behaviors, id reuse, restart semantics) becomes one
behavioral test with the expectation captured from the real controller.

## Safety rails

Namespaced artifacts only; never touch existing devices/globals; settings
PUTs restore their old values; dry-run listing; the existing auth-lockout
guard stays.

## Order

A/B first (broad, safe coverage while a controller is available), then C/D
(the deep parity + the capture that outlives the availability window), then
E as quirks surface. All plumbing exists (Hc3Remote, EnvChain, opt-in
gating, sim Api); the work is test code + one capture script.
