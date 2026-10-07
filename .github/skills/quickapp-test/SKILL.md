---
name: quickapp-test
description: How to test and verify a QuickApp offline with flua, without the flua repo or Python tooling. The QA is its own test: assert inside the QA, exit with the failure count, check the exit code; drive UI events and device actions over the HTTP sim API (--ui), use deterministic virtual time and --seed. USE FOR: testing a QA, verifying a change, checking QA behavior offline, writing self-asserting QAs, driving the simulated HC3 from a script or agent.
---

# Testing QuickApps with flua (offline)

flua runs a QA against a simulated HC3 — no controller, no repo needed. The
QA itself is the test harness: it asserts its own behavior and exits with a
code the caller (shell, CI, or an agent) checks. Runtime errors also exit
non-zero, so no code path silently passes.

## The verification loop

```bash
flua --check qa.lua              # 1. static: syntax, --%% directives, deprecated APIs
flua --api local qa.lua          # 2. run offline; the QA must exit itself
echo $?                          # 3. exit code: 0 = pass, non-zero = fail
```

- The run lasts until the QA calls `exit(0)` / `os.exit(0)` (HC3 names) — a
  QA that never exits runs forever, so every test QA must end with an exit.
- `exit(N)` exits with N; an uncaught Lua error exits 1.
- Several QA files can run in one flua process (each isolated, its own
  device id from 5000): `flua --api local a.lua b.lua`.

## Self-asserting QA pattern

```lua
--%%name:my_qa_test
local failures = 0

local function assertTrue(cond, msg)
  if cond then print("PASS: " .. msg)
  else failures = failures + 1; print("FAIL: " .. msg) end
end

local function assertEq(actual, expected, msg)
  if tostring(actual) == tostring(expected) then
    print("PASS: " .. msg .. " (" .. tostring(actual) .. ")")
  else
    failures = failures + 1
    print("FAIL: " .. msg .. " — expected " .. tostring(expected) .. ", got " .. tostring(actual))
  end
end

function QuickApp:onInit()
  local device = api.get("/devices/" .. self.id)  -- the sim sees the QA
  assertEq(device.id, self.id, "device visible in the sim")

  self:updateProperty("value", 50)
  assertEq(self.properties.value, 50, "updateProperty round trip")

  print("failures:", failures)
  exit(failures > 0 and 1 or 0)
end
```

A ready-made example ships with flua: `flua --examples` prints the examples
directory — run `examples/selfTest.lua`. Read updated properties back via
`self.properties.<name>` (in flua, `updateProperty` does not create a
`self.<name>` field).

## Driving interactions over HTTP (`--ui`)

When the logic under test needs UI events or device actions, serve the sim
API and drive it with curl (or any HTTP client):

```bash
flua --api local --ui 8090 qa.lua &    # sim API + UI viewer on :8090

# UI event (what the HC3 UI sends; value optional, multi selects comma-joined)
curl "http://127.0.0.1:8090/plugins/callUIEvent?deviceID=5000&elementName=B1&eventType=onReleased"
curl "http://127.0.0.1:8090/plugins/callUIEvent?deviceID=5000&elementName=slider&eventType=onChanged&value=42"

# device action
curl -X POST -H "Content-Type: application/json" \
  -d '{"args":["42"]}' http://127.0.0.1:8090/devices/5000/action/setValue

# inspect state: properties + view (updateView target), device list, live layout
curl http://127.0.0.1:8090/devices/5000
curl http://127.0.0.1:8090/flua/devices
curl "http://127.0.0.1:8090/plugins/getView?id=5000"
```

The QA's PASS/FAIL output goes to the flua process's stdout. Kill the
background flua when done.

## Deterministic virtual time

Timer logic must be reproducible — never sleep in a test QA:

```bash
flua --api local --start '2027/10/6 12:00:00' qa.lua   # fixed start time
flua --api local --speed 60 qa.lua                     # 60x virtual speed
flua --api local --instant qa.lua                      # timers fire immediately
flua --api local --max-hours 24 qa.lua                 # bound the run
```

## Mock the outside world (`net.*Server`)

flua extension (no HC3 counterpart): the QA itself can host the services its
clients talk to, so HTTP/TCP/UDP/WebSocket logic is testable offline with no
Python. Handler runs on each request; its return value is the reply:

```lua
local http = net.HTTPServer()
http:listen(0, function(req)  -- {method,url,headers,body}
  return {status=200, body="ok", headers={["X-Mock"]="1"}}  -- or a string, or nil (204)
end)
local tcp = net.TCPServer()      -- tcp:listen(0, function(data) return data:upper() end)
local udp = net.UDPServer()      -- udp:listen(0, function(data, ip, port) return "got:"..data end)
local ws = net.WebSocketServer() -- ws:listen(0, function(msg, isBinary) return "echo:"..msg end)
-- port 0 = free port; read server.port
net.HTTPClient():request("http://127.0.0.1:" .. http.port .. "/x", {
  success = function(resp) print("mock answered", resp.status, resp.data) end,
})
```

One-shot request/response semantics: the TCP handler sees the first data
package, UDP one datagram, WS one message (binary replies come back as
binary frames). Handler errors reply `500` (HTTP); no reply within 10 s is
`504`. `server:close()` stops a server; servers die with their QA. Canonical
self-test: `examples/mockServer.lua` (`flua --examples` prints the dir).

Handlers are plain closures — they can keep mock state across requests
(`local hits = 0`), branch on `req.url`, and call `api.get` etc. like any QA
code. The reply is the handler's *synchronous* return value, so a mock
cannot simulate latency; for client-timeout tests use an unreachable port or
close the server before the client connects.

Mock code can live in a separate file next to the QA: `require("mocklib")`
finds `mocklib.lua` in the QA's directory and is **not** packaged into the
`.fqa` (only `--%%file` files ship) — keep test scaffolding out of what gets
deployed to the HC3.

## Seeding the simulated HC3

`--seed FILE` loads a JSON world: `{"devices": [...], "rooms": [...],
"scenes": [...], "globalVariables": {...}}` — give the QA devices to talk
to, then assert on the resulting calls and state.

## Gotchas

- Offline is the default; `--api local` makes it explicit and immune to a
  stray `--%%mode:online` (which needs HC3 credentials).
- `self:updateProperty` lands in `self.properties.<name>` — read it back
  there.
- Multi selects deliver `event.values[1]` as the *list* of selected values
  (HC3 contract); empty lists must be `json.array()` so they encode as `[]`.
