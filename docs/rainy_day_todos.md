# Rainy-day todos

Non-urgent, nice-to-have improvements — agreed as valuable but parked
until a natural moment (or a second user request). Each entry keeps the
rationale from the triage so the context survives. Remove an entry when it
ships; the date marks when it was parked.

Parked 2026-10-31, from the forum feedback triage (docs/feedback/):

## Network policy — deny/loopback gate (Change 04, simplified)

- **What**: an opt-in `--network-policy deny|loopback` (and a
  `--no-user-config` for inherited credential/config discovery) applied at
  flua's transport boundary — HTTP/WebSocket/TCP/UDP. Deny before connect.
- **What NOT to build**: the full proposal's allowlists, DNS-resolution
  checks, redirect rules, IPv4/IPv6 parity. A wrong network policy sells
  false confidence, and it is accident-prevention, not a security sandbox
  (a hostile QA runs in-process).
- **Rationale**: real value for running foreign/untrusted QAs (the pt
  report ships its own audit-hook wrapper for exactly this); the 80%
  version covers the accident risk.
- **Pinning test**: loopback fixture works; external target fails before
  connect; background retries respect the policy; no live devices.

## Export preview — `--manifest-only` (Change 07)

- **What**: `flua export ... --manifest-only` — the files and variable
  names the package would ship, value origins (expression/config file),
  and whether values would be embedded — without printing resolved secret
  values.
- **Rationale**: export-safety glance for the distribution workflow; low
  effort. flua already has the placeholder/bake machinery, so this is
  presentation, not new resolution logic.

## Resource summary (Change 09, the small half)

- **What**: `--resource-summary` — pending timers, owned HTTP requests,
  subscriptions, queue lengths, before/after stop or restart. Leak and
  lifecycle debugging.
- **What NOT to build**: the full event-trace file (registration/due/
  delivery/cancellation correlation, generation ids) — `--trace
  api,ui,net,timer` + syslog/timeline already cover most of it.
- **Rationale**: small, real debugging value; the full trace would be
  re-doing the existing trace channel at medium cost.

## Documentation asks from the pt report

- **Windows/locale guide**: largely resolved — the engine now forces
  `LC_CTYPE=C.UTF-8` (falling back to `C`) before the Lua runtime exists
  (the plua 1.2.79 fix: Lua's pattern classes are libc ctype lookups, so
  Polish/Windows locales split multibyte characters in `%S+`; C.UTF-8
  rather than plain C so embedders keep `locale.getencoding()=UTF-8`);
  `--version --machine` reports both `locale` and the effective `ctype`.
  Known platform limit, documented: macOS's C.UTF-8 still classifies
  high bytes as `%a`. Remaining: a short doc on byte-pattern
  classification and UTF-8 handling on Windows (interpreter selection,
  `-X utf8` for the MCP setup subprocess).
- **UI/export fidelity guide**: what simulated UI events and string values
  can and cannot establish about real HC3/browser/mobile rendering; legacy
  vs newer UI export; select defaults.
- **Lifecycle/observability guide** (or skill): pending resources and
  late-callback fencing across stop/restart — likely folds into the
  resource summary above.

## Batch C leftovers already rejected (do not resurrect without new evidence)

- Full network allowlist/DNS/redirect machinery (Change 04 full).
- Second, richer event-trace format (Change 09 full) — the existing
  `--trace` channel wins on maintenance cost.

## From the pt additional proposals (parked 2026-10-31, A01–A10)

The author framed these as optional, non-defect proposals. Honest verdict:
they are **harness-layer features**, and most of them are better built on
top of flua's primitives than inside the emulator. flua already offers the
foundations: scripted transports via local mock servers (the tests do this
everywhere), `--strict-tests` + `--result-json`, `--%%replay`/`flua record`,
`--%%db` seeding, the migrate tool, `--check`, and `--trace
api,ui,net,timer`. None of A01–A10 blocks real work.

- **A01 slow-controller/constrained-dispatch profiles** — synthetic REST
  latency/queue models. Valuable for exposing timing bugs, but a
  fault-injection framework of its own; park until someone asks twice.
- **A02 scripted transport completion** — partially available today
  (local mock HTTP/WS/TCP servers can already script delays, disconnects
  and duplicate notifications; the repo's tests do this). The missing
  piece is a reusable, declarative scripting layer — park.
- **A03 restart injection** — `plugin.restart` and the restart tests exist;
  the checkpoint/sequence-number injection harness does not. Park.
- **A04 write-volume diagnostics** — the only small, self-contained item:
  a write counter (by QA/target/operation, attempts vs changes). Good
  candidate for a small implementation; shortlist it.
- **A05 migration fixtures** — overlaps `--%%db` seeding + the migrate
  tool; the synthetic-inventory builder + before/after comparison is new.
  Park.
- **A06 correlated latency** — overlaps `--trace timer,net`; the
  stage-by-stage operation-ID correlation is new. Park.
- **A07 lifecycle resources** — already filed above (resource summary,
  Change 09-half). Merged, no new entry.
- **A08 seeded async scenarios** — overlaps `--%%replay`/`flua record`.
  Park.
- **A09 source-vs-package differential testing** — overlaps pack/unpack
  round-trip tests; the observation-diff harness is new. Park.
- **A10 structural UI validation** — overlaps `--check` and the uiView
  machinery; the validation rules (unique names, callback targets, update
  budgets) are new and modest — shortlist alongside A04.

## Extensibility: stabilize the embedding surface + three edge hooks (parked 2026-10-31)

From the "Python plugin mode with SDK?" discussion. Verdict: build targeted
edge hooks, not a general plugin framework — flua's moat is trustworthiness,
and every plugin boundary risks it.

- **Stabilize and document the embedding surface** — `LuaEngine` (constructor,
  `api.dispatch`, state access, the bridge rules) is already the de-facto
  SDK (the MCP server, the tools and external harnesses all drive it); the
  pain point in feedback is that it is *internal* and may change. Document
  it, name what is stable, keep the rest internal.
- **`--tool` plugin directory** — auto-discover tool modules from a user
  directory alongside the in-package registry (the registry already
  auto-discovers; pointing it at an extra path is trivial).
- **Custom REST route registration** — SHIPPED (2026-10-31):
  `api.registerEndpoint(method, pattern, handler[, override])` with
  built-in override and cross-QA routing (a mock panel deployed as a QA
  answers every QA's calls). What remains deferred from this item:
  transport/server-kind registration (new `net.*Server` protocols — the
  engine's server dispatch is hardcoded).
- **Lua `require` path/preload injection** — a plugin dir on the QA's
  `package.path`/preload registry, so shared Lua libraries come from a
  plugin instead of per-project copies.
- **Deferred until someone needs it twice:** transport/server kind
  registration (new `net.*Server` protocols — the engine's server dispatch
  is hardcoded).
- **Refused:** a full plugin lifecycle (sandboxing/loading/versioning —
  no security story exists in-process, and it is permanent API surface);
  hooks into the pump/scheduler/clock (where the invariants live).

## Pump wake-up, event-driven (parked 2026-11-03)

- **What**: replace the pump's idle polling entirely — an `asyncio.Event`
  set by `enqueue_outbound` (with `call_soon_threadsafe` from the worker
  threads) so the pump sleeps until there is actual work.
- **What NOT to touch blindly**: the `get_nowait()` drain loop exists
  because `wait_for(queue.get(), timeout)` lost messages on Python <= 3.12
  (ADR 0006, CI failures) — an event wake-up must keep the drain semantics
  and earn trust on the full 3.11-3.15 CI matrix.
- **Rationale**: shipped the cheap 80% first (the adaptive idle poll:
  `_PUMP_POLL_IDLE` when no timers are pending); the event-driven version
  removes the remaining ~20 wakeups/sec but rewrites the most delicate
  part of the engine.

## QA id band — HC3 devices approaching 5000 (parked 2026-11-03)

- **What**: the real HC3's QA ids never get reused, and one user's controller
  is already at 4357 — once real device ids cross 5000 they collide with
  flua's emulated QA ids (engine-assigned from 5000). The fix, in order of
  leverage:
  1. *Cheap insurance*: in online/hybrid mode the allocator consults the
     real HC3's /devices id set when skipping (today it only skips ids in
     the sim's own state) — collision becomes impossible without any
     configurability.
  2. *Shape-based QA detection*: `api/state.py:is_plugin_device()` uses
     `id >= 5000`; replace with device-shape markers (quickAppVariables /
     view / uiView), which also makes everything base-agnostic.
  3. *Configurable base*: a `qaIdBase` knob (`.flua.lua` / CLI flag) for
     users who want a clean id band — the seed point is a single line
     (`engine.py:_next_qa_id`).
- **What NOT to worry about**: the blast radius is small — one seed point,
  one id-range heuristic, the online allocation gap; tests keep the default
  base and stay green.
- **Rationale**: parked at the owner's request ("we can wait a bit longer
  until we go there"); items 1-2 are worthwhile insurance before any
  configurability.

## Copilot Skoda feedback — discovery and verification asks (parked 2026-11-11)

From `docs/feedback/flua-feedback_copilot_skoda.md` — a from-scratch agent
build of the Skoda pair in a pip-only workspace, with the bundled example
excluded. Already shipped from that report: the generic mock-QA recipe in
quickapp-patterns, the flua-setup default-mode wording fix, and structural
assertion totals in `flua test --json`.

- **Docs lookup (the #1 ask)** — `docs_search` (excerpts + stable section
  ids), `docs_read` with heading/line ranges and output caps, task-oriented
  entry points ("mock an HTTP service"). `docs_list` is 51 KB today; the
  agent did filesystem archaeology instead of MCP reads.
- **Agent-facing tool map** — one compact response listing every MCP tool
  with exact names and example calls; invalid-argument errors should carry
  a valid example.
- **Virtual time vs real I/O recipe** — how `--step` advances while socket
  I/O is pending; an `eventually(predicate, timeout)` helper and an
  awaitable request helper for test QAs. Reconfirmed by the Sonos offline
  suite report (docs/feedback/sonos_flua_26_11_13.md): the #1 friction —
  at `--speed 50` a 300 ms virtual delay is ~6 ms wall, shorter than a
  localhost round-trip, so fixed-delay waits fail everywhere; wall-paced
  messages spread out in virtual time, so poll timeouts must scale with
  `--speed`. Ask shape: a `t:waitFor(cond, timeout, cb)` in flua-test plus
  the (now added) skill warning. The pipe-buffering false-hang note is
  documented in the test skill.
- **ws mock deferred replies** — the ws handler's reply is synchronous-only;
  a sentinel + `ws:reply(conn, data)` would enable reply-latency/
  reordering/timeout tests against the client's request queue (SonosLib's
  30 s command timeout is untestable without it). Event latency already
  mocks via `setTimeout` + `ws:send`.
- **flua-test verdict visibility** — PASS/FAIL lines emit at DEBUG level
  with the standard prefix; a mode where verdicts stand out (level/tag) in
  plain text would make `grep FAIL` pipelines cleaner (CI use).
- **Pack verification** — SHIPPED (the two repeated asks merged):
  `--tool inspectFQA FILE [--json]` (metadata, file inventory, the
  apiVersion marker, placeholder-vs-baked variables, UI surface, IP leak
  scan) and `--tool pack --verify` (the same inspection right after
  packing plus the declared-placeholder check). The remaining sliver, if
  ever wanted: a full source-aware diff of the packed main against the
  source (byte-compare is wrong — the bake rewrites --%%var lines).
- **Skill installation vs invocation** — workspace skill files and the
  editor's skill loader can disagree; a setup/doctor check should report
  which skills are local docs vs registered, and how to load each.
- **Version-stamped agent docs** — skills/instructions carrying their
  source version + an offline freshness check; the report found conflicting
  default-mode statements between surfaces.
- **Verification-layer boundaries** — tool summaries should say what each
  check proves (static ≠ runtime; mock ≠ car; `_FLUA` removal tests branch
  logic, not firmware).
- **Simplify the upload wire format** — with `initialProperties.apiVersion`
  in every flua-packed .fqa (the real HC3 format marker, live-verified),
  the tools could drop the multipart `/quickApp/import` path and use the
  plain JSON create like plua does. Parked by decision (2026-11-11): the
  import endpoint stays as belt-and-braces. When revisited: switch
  uploadFQA/uploadQA/installHelper/proxy to the JSON create, keep
  `Hc3Remote.multipart` only if still needed, keep the sim's multipart
  parsing + the skill's multipart recipe as the marker-less-package
  fallback.

Parked 2026-11-12, from the custom-icon work (User<id> sets, uploadExternalIconSet):

## QA self-installs its own icon set (idempotent, no stored state)

- **What**: an example QA + quickapp-patterns skill section for "ensure my
  icon set exists": on init, `api.get("/icons")` -> filter `deviceType ==
  self.type` and `iconSetName` starting with `User`; fetch each candidate's
  state file via `net.HTTPClient` from
  `http://127.0.0.1/assets/userIcons/devices/<set>/<set><state>.png`
  and byte-compare with the bundled icon; match -> already installed ->
  `updateProperty("deviceIcon", id)`; no match -> `uploadExternalIconSet`
  -> new id. Replaces the quickVar/internalStorage "already downloaded?"
  bookkeeping that went stale on QA reinstall (duplicate sets, lost ids).
- **Ground truth (live-verified 5.22x)**: the HC3 serves uploaded icon
  files byte-identical (md5-equal) under `/assets/userIcons/devices/`; the
  fibaro tree is placeholder art for User sets; binary/multilevel sets have
  no base file, only state files; the named shutter states serve under the
  same `<set><state>.png` naming (live-verified with a baseShutter set,
  id 1111); icons must be >= ~128x128
  (`INVALID_ICON_SIZE` otherwise); POST `/api/icons` multipart contract:
  `type=device`, `deviceTemplate=<type>`, file fields per the provider
  (`icon`/`icon0`+`icon100`/`icon0..100`/`iconOpening...`), response
  `201 {"id":N,"iconSetName":"User<N>","fileExtension":"png"}`.
  DELETE contract (mined from the web UI's Angular bundle + live-verified):
  `DELETE /api/icons?type=<device|room|scene>&id=N&name=<set>&fileExtension=<ext>`
  — `type` is the icon CATEGORY (not deviceType; WRONG_TYPE otherwise),
  `id` is required (MISSING_PARAMETER); 200 + empty body on success. POSTs
  to unknown /api/icons/* paths HANG the connection — never guess there.
  (`flua --tool icons ui` — the icon manager — builds on all of this.)
- **The 11111/11112 split (probed from a QA on the controller, settled)**:
  through `api.get("/proxy?url=http://localhost:PORT/<path>")`, **11112**
  is the full local API — JSON bodies that `api.get` decodes into Lua
  tables (synchronous + credential-free recipe for GETs). **11111**
  answers 200 with non-JSON bodies for such GETs (`nil, 200` after the
  decode step); its one established use is Fibaro's own `uploadIconFiles`
  (POST `http://127.0.0.1:11111/api/icons`). **Neither port serves the
  asset tree** — `net.HTTPClient` to `127.0.0.1:11112/assets/...` 404s
  ("The requested method does not exist"), 11111 501s. The real icon
  source is the plain web server: `http://<hc3>/assets/userIcons/devices/...`
  on port 80, served by nginx **credential-free** (verified both from a QA
  on the controller and externally) — that is the canonical icon-fetch
  recipe, and flua online rewrites `127.0.0.1` to the controller keeping
  port 80 with no auth.
- **flua emulation divergences found along the way**: (1) FIXED —
  `net.HTTPClient` and the `/proxy` fetcher corrupted binary bodies (the
  utf-8-replace decode inflated a 2442B PNG to 4829B of mojibake):
  responses now travel as raw `bytes` (lupa carries them into Lua strings
  unchanged; a str channel cannot be byte-faithful — even latin-1 doubles
  up at the bridge). Pinned by binary `/blob` tests. (2) flua rewrites
  11111 and 11112 identically to the standard API — faithful for 11112,
  too lenient for 11111 GETs (the controller answers non-JSON there).
  (3) `api.get("/proxy?...")` of a binary body returns the raw bytes
  where the HC3 nils it — kept as a deliberate flua extension (the bytes
  are what recipes need); document it. (4) flua's `/proxy` route ignores
  the HC3's `username`/`password` query parameters (Fibaro's own
  `getProxyUri(uri, login, password)` helper — the undocumented
  target-auth surface; no user code seen using it yet). Fix when needed:
  prepend them as userinfo in `proxy_get` so `fetch_url`'s existing
  userinfo→Basic path applies; pin with a mock-server test.
- **Flua angle**: recipe is online-only (needs `/api/icons` + the 11111
  loopback; the sim has the catalog route but no asset tree — degrade
  gracefully). Testable against the mock HC3. Related parked options from
  the same session: a `_FLUA.saveIcon(set, file, bytes)` bridge call and
  lazy fetch+cache in the icon channel (online/proxy) so the viewer warms
  the cache on demand — both "wait for now".
