# Testing the Sonos QA offline with flua — experience report

Date: 2026-11-13 · flua 0.1.161 → 0.1.164 · macOS, Python 3.11.13

## Context

Follow-up to [sonos_flua.md](./sonos_flua.md) (the plua→flua conversion and
the SSL-write debugging session). This round had a different goal: the family
was home, so the real players were off-limits — build a **fully offline
regression suite** for SonosLib instead. That meant mocking the Sonos local
WebSocket API (`wss://<player>:1443/websocket/api`) inside the emulator:
request/reply commands, *and* server-initiated event pushes
(`playbackStatus`, `groupVolume`, `metadataStatus`, `versionChanged`,
`groups`), *and* the drop-subscriptions-on-disconnect semantics a real
player has.

## Outcome

A pure-Lua mock player (`dev/sonosmock.lua`, ~300 lines) and a 36-assertion
flua-test suite (`dev/test_sonos.lua`) that runs in ~30 s wall at
`--speed 50`, exit code as verdict. It caught a real long-standing bug
(SonosLib never resubscribed after a reconnect — events silently stopped
forever) and proved the fix with a negative test: disable the fix, exactly
the reconnect assertions fail. Also filed jangabrielsson/flua#3 for the one
missing capability (ws server push); it was implemented and released in
0.1.164 the same day, and the mock's final form sits entirely on it.

## What worked well

1. **`net.WebSocketServer` + the new push surface (0.1.164)** is exactly the
   right shape for mocking event-driven protocols. `handler(message,
   isBinary, conn)` matching the TCP server's signature, `ws:send(conn,…)`,
   `ws:disconnect(conn)`, and `connected`/`disconnected` listeners were all
   the mock needed — per-connection subscription state, pushes to
   subscribers only, and a server-side drop to exercise the client's
   reconnect path. Nothing felt bolted on.

2. **The ws *client* needed zero accommodation.** TLS is driven by the URL
   scheme, so `net.WebSocketClientTls` happily speaks plain `ws://` to the
   mock on 127.0.0.1. The only product-code change for testability was a
   3-line seam in SonosLib (accept a full URL instead of a bare IP) — and
   coordinator URLs come from the mock's own `getGroups` reply anyway, so
   the mock controls nearly all routing by construction.

3. **The sibling-file `require` pattern** (`if require then
   require("sonosmock") end`) is a great convention: the mock runs in the
   QA's own env with full `net.*`/timer access, and it *cannot* leak into
   the packaged `.fqa`. Verified: the packed artifact contains no mock, no
   test code, and (with the `--%%var` package-value form) no real IP.

4. **`flua-test`** is small and sufficient: `t:expect`, deep `assert_eq`,
   `t:finish()` printing the summary and exiting with the failure count.
   Exit-code-as-verdict composes perfectly with CI and with `--run-for` as
   a safety cap.

5. **Virtual time at `--speed 50`** compressed a suite that includes a 3 s
   reconnect timer into a ~30 s wall run, with no changes to the code under
   test. `--run-for N`'s semantics (wall cap → exit 1 with work pending)
   turned a would-be hang into a diagnosable failure on the first broken
   run.

6. **The issue → release loop.** Reported the ws-push gap with a proposed
   API in the morning; 0.1.164 shipped it (plus docs in USAGE's mock-server
   section and a round-trip test upstream) the same day. The implemented
   surface matched the proposal almost verbatim, so the mock written
   against the proposal needed no rework.

7. **`flua --tool ui`** statically rendered the declared UI — instant
   verification that a new multi-button row (`--%%u:{{button=…},{button=…}}`)
   parsed as one row with four callbacks, without running the QA (which
   would have touched the real network).

8. **Pack-time variable policy worked as documented.** The package-value
   form `--%%var:IP='192.168.50.5',"<Sonos player IP>"` baked the
   placeholder into the distributed `.fqa` and rewrote the main file's var
   line to the literal — a 5-line Python check confirmed no real IP
   anywhere in the JSON.

## Friction — what could be improved

1. **Virtual time vs. wall-clock I/O is the big one.** Socket round-trips
   happen in wall time; timers in virtual time. At `--speed 50`, a 300 ms
   virtual delay is 6 ms wall — shorter than a localhost ws round-trip — so
   a naive "command, wait 300 ms, assert" suite failed everywhere while the
   system under test was fine. The fix (poll the condition every 100 ms
   virtual with a generous timeout) is easy *once you know*, but everyone
   writing network-QA tests will hit this. Suggestions:
   - a `t:waitFor(cond, timeout, cb)` (or promise-style) helper in
     flua-test, so condition-polling is the paved road;
   - a prominent USAGE/skill note: "at high `--speed`, never use fixed
     delays to wait for network effects".

   A related second-order effect: wall-paced messages *spread out* in
   virtual time (13 resubscribe frames ≈ 10 ms wall apart logged as ~500 ms
   virtual apart at speed 50). Harmless once understood, but it makes
   virtual-timestamped logs look like the client is being slow, and it
   means poll timeouts must scale with `--speed`.

2. **The ws server reply is synchronous-only.** The handler's return value
   is the reply, so a mock cannot delay a *reply* (pushes can be delayed
   via `setTimeout` + `ws:send`, which covers most cases). A deferred-reply
   option (e.g. return a sentinel, answer later via `ws:reply(conn, data)`)
   would enable latency/reordering/timeout tests against the client's
   request queue — SonosLib's 30 s command timeout is currently untestable
   without it.

3. **Skill docs lagged the release.** USAGE.md documented the new push
   surface on day one, but the `quickapp-test` skill still described the ws
   mock as "one message in, optional reply out". Minor, but agents (and
   humans) often read the skill first; a release checklist item "grep the
   skills for the old behavior" would catch it.

4. **PASS/FAIL lines are emitted at DEBUG level** with the standard
   timestamp/tag prefix. Fine interactively, slightly noisy for CI. A
   `--log json` run gives structure, but a plain-text mode where test
   verdict lines stand out from QA debug chatter (different level or tag)
   would make `grep FAIL` pipelines cleaner.

5. **Piped output buffering masked a first-run hang.** `flua … | tail -50`
   showed nothing for two minutes (tail buffers until EOF), which read as
   "emulator hung" when the run was actually progressing. Not flua's fault,
   but a `--quiet`/progress-to-stderr hint in the test-skill docs would
   save the next person the false alarm.

6. **Pack verification is DIY.** The post-pack checklist (right name/type,
   placeholders present, no secrets/IPs in the JSON) is documented but
   manual. A `flua --tool pack … --verify` (print name/type/vars, scan for
   values that look like the *evaluated* secrets it just replaced) would
   turn the checklist into a flag.

## Verdict

The gap between the two reports is striking. Last time flua was the
debugging instrument for a transport bug; this time it was a complete
offline test *platform*: a protocol mock, virtual-time execution, assertion
library, static UI inspection, and leak-checked packaging — with the one
missing primitive shipped upstream within hours of being named. The
remaining friction is concentrated in one conceptual spot (virtual time
meets real I/O) and is documentation/helper-shaped, not architecture-shaped.
The Sonos QA now has family-safe CI.
