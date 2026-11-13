# Debugging the Sonos QA with flua — experience report

Date: 2026-10-31 · flua 0.1.107 → 0.1.109 · macOS, Python 3.11.13

## Context

Debugging `SonosPlayer` (a `com.fibaro.player` QA backed by SonosLib 0.90) that
reported intermittent communication errors. The QA talks to the Sonos local
WebSocket API (`wss://<player>:1443/websocket/api`) over up to four concurrent
connections (household + one per player coordinator), sends bursts of
subscribe commands at connect, and then waits for server events.

The same `.fqa` ran fine on the HC3, so the problem was in the emulator's
`net.WebSocketClientTls` layer. flua was the primary debugging tool throughout.

## Outcome

Found a real flua bug: each `wsSend` message spawned its own asyncio task that
ran the send in the default thread pool, so a burst of sends from Lua produced
concurrent `SSL_write` calls on one `SSLSocket`. CPython's ssl layer is not
safe for concurrent writers; the TLS record stream got corrupted. Symptoms
were exactly what the QA showed:

- `[SSL: BAD_LENGTH] bad length (_ssl.c:2437)`
- `EOF occurred in violation of protocol (_ssl.c:2437)`
- `[SSL] called a function you should not call (_ssl.c:2437)`

followed by the player closing the socket (WS close 1000) and a
disconnect/reconnect loop with 30 s command timeouts.

Verified in 0.1.109: burst test 3/3 clean (was 3/3 broken), full QA run 90 s
with zero disconnects/errors. The upstream fix (write lock, blocking receiver
reads with `SO_SNDTIMEO`, close-frame dedup) also addressed the two secondary
issues found along the way.

---

## What worked well

1. **Offline mode with real network** ("sim HC3, real network") was the single
   most important enabler. The QA's own `net.WebSocketClientTls` calls reached
   the real Sonos player on the LAN, so the exact HC3 code path ran against the
   exact real device — without the HC3. This hybrid mode is not obvious and
   deserves prominent documentation.

2. **`--%%debug:ws=true` byte-level trace.** Indispensable. It showed every
   tx/rx frame with size and masked preview, the 101 handshake, and the server
   close code (1000). Without it the failure would have looked like a random
   Sonos disconnect. Secret masking in previews is appreciated.

3. **`flua --check`** caught a directive syntax bug in seconds
   (`--%%file` colon form in a migrated plua-era test file).

4. **`downloadQA`** made it trivial to inspect what was actually deployed on
   the HC3 and diff it against the workspace.

5. **Installation layout made hypothesis-testing fast.** `websocket.py` is
   stdlib-only and lives in `site-packages`, so I could apply a two-line test
   patch locally, re-run against the player, and prove the fix before it went
   upstream. (Upstream 0.1.109 later replaced the patch cleanly.)

6. **Reproducibility of the bug.** A minimal 25-line QA (7 sends on connect)
   reproduced the failure 100%, which turned the fix into a regression test.

7. **`--run-for` + `_FLUA.exit()`** gave clean bounded runs for repro QAs.
   `--version` output includes the interpreter (Python 3.11.13) — mattered
   here, since ssl behavior was the suspect.

8. **AGENTS.md pack-verify loop** (pack → inspect JSON) worked exactly as
   documented; the regenerated `.fqa` checked out (name, baked IP variable,
   lib version, guard present).

## What could improve

1. **WS trace lines don't identify the connection.** With 2–4 concurrent
   sockets the trace is flat (`ws tx text 106b …`) with no conn id or host.
   I had to correlate by timestamp and cmdId. Suggest a per-line prefix like
   `ws[c3 192.168.50.223] tx …`, and include the conn id in `wsEvent`/`error`
   payloads. (SonosLib colors its own logs per coordinator; flua's trace was
   the only stream without an identity.)

2. **No CLI flag to enable debug channels.** `--%%debug:ws=true` is header-only,
   so enabling the trace meant copying the QA file and editing its header.
   Suggest a CLI override (`--debug ws` / `--debug=ws=true`).

3. **Confusing diagnostic for legacy `--%%file:path:name`.** The check error
   was `--%%file:SonosLib.lua:SonosLib,SonosLib.lua:SonosLib: no such file: …`
   — a doubled path that didn't tell me the colon form is the old syntax.
   A migration hint ("use `--%%file:path,name`") would have saved a detour.

4. **No tool for probing a WebSocket endpoint outside a QA.** Isolating
   player behavior from emulator behavior required hand-rolled Python probes
   (raw handshake, pipelined subscribes, 150 s soak). A `flua --tool ws`
   (handshake / send N frames / subscribe / soak with ping-pong) would replace
   that and make "is it the device or the emulator?" a 30-second answer.

5. **Docs gap: debugging real communications.** Neither AGENTS.md nor the
   docs I found mention that offline mode uses real network for `net.*`, or
   that `--%%debug:ws=true` exists, or what its output looks like. A short
   "debugging real device comms" section (offline + real network, ws trace,
   `--run-for`, `_FLUA.exit`) would have cut the discovery phase significantly.

6. **Send-failure events carry no payload context.** The Lua `error` event got
   only the Python exception string; when a burst corrupts, you can't tell
   which send failed. A masked preview of the failed frame (the masking logic
   already exists) would close that gap.

7. **Minor, fixed in 0.1.109:** on server close the client echoed a close
   frame and then `close()` sent a second one (trace showed `tx close 2b`
   followed by `tx close 0b`); receiver used 0.5 s `settimeout` polling which
   could land mid-TLS-record.

## Missing info / skills

- **No guidance on testing QAs against real LAN devices.** The offline+real
  network hybrid is powerful but undocumented; I only discovered it from the
  startup banner.
- **No network-protocol skill or pattern doc.** Existing skills cover UI
  testing and REST APIs; nothing covers "connect → burst → watch disconnect
  → assert stability" for socket protocols, or how to write a bounded repro QA
  (`--run-for` + `_FLUA.exit`).
- **The `net` trace events** (`wsConnect`, `wsEvent`, per-frame bytes) exist in
  the engine but I never found them documented; a doc line pointing at
  `--log json` / trace output would help.

## Observations on the QA itself (found via flua, not flua's fault)

- SonosLib reconnects the socket after a drop but never re-sends its
  subscriptions (the send buffer flushes once on first connect). After any
  reconnect the QA goes deaf until restart — the flua bug made this visible
  because drops were constant. Worth fixing in SonosLib.
- `metadataStatus` handler crashed on tracks without an artist
  (`attempt to index a nil value (field 'artist')`) — nil-guard added.

## Appendix: minimal repro (burst sends on connect)

```lua
--%%name:WsTest
--%%type:com.fibaro.binarySwitch
--%%debug:ws=true
local KEY = "..."  -- any value the device accepts

function QuickApp:onInit()
  local sock = net.WebSocketClientTls({timeout=10000})
  sock:addEventListener("connected", function()
    print("CONNECTED, sending 7 rapid subscribes")
    for i=1,7 do
      local msg = {playerId="<player-id>", namespace="playerVolume",
                   command="subscribe", cmdId=tostring(i)}
      sock:send(json.encode({msg,{}}))
    end
  end)
  sock:addEventListener("dataReceived", function(d) print("RX:",d:sub(1,80)) end)
  sock:addEventListener("disconnected", function()
    print("DISCONNECTED"); setTimeout(function() _FLUA.exit(0) end, 2000)
  end)
  sock:addEventListener("error", function(err) print("ERROR:",err) end)
  sock:connect("wss://192.168.50.223:1443/websocket/api", {
    ["X-Sonos-Api-Key"] = KEY,
    ["Sec-WebSocket-Protocol"] = "v1.api.smartspeaker.audio",
  })
  setTimeout(function() print("10s watchdog"); _FLUA.exit(0) end, 10000)
end
```

Before the fix this disconnects after 1–2 responses; after the fix all 7
responses arrive and the connection stays up.
