--%%name:mock_server
-- mockServer.lua — flua's net.*Server mock servers, self-tested
--
-- flua extension (no HC3 counterpart): a QA can HOST HTTP/TCP/UDP/WebSocket
-- servers to mock the services its net.* clients talk to — no Python, no
-- repo. The handler runs on each request; its return value is the reply.
-- All servers bind 127.0.0.1; port 0 picks a free port (server.port).
--
-- Run it offline:  flua --api local examples/mockServer.lua
-- The QA exercises all four client transports against its own mock servers
-- and exits with the failure count. See the quickapp-test agent skill.

local failures = 0

local function assertEq(actual, expected, msg)
  if tostring(actual) == tostring(expected) then
    print("PASS: " .. msg .. " (" .. tostring(actual) .. ")")
  else
    failures = failures + 1
    print("FAIL: " .. msg .. " — expected " .. tostring(expected) .. ", got " .. tostring(actual))
  end
end

local pending = 4
local function done()
  pending = pending - 1
  if pending == 0 then
    print("failures:", failures)
    exit(failures > 0 and 1 or 0)
  end
end

function QuickApp:onInit()
  -- the mocks: one server per transport
  local http = net.HTTPServer()
  http:listen(0, function(req)
    if req.url == "/hello" then
      return { status = 200, body = "Hello " .. req.body, headers = { ["X-Mock"] = "1" } }
    end
    return { status = 404, body = "not found" }
  end)

  local tcp = net.TCPServer()
  tcp:listen(0, function(data)
    return data:upper()  -- first data package in, reply out, connection closes
  end)

  local udp = net.UDPServer()
  udp:listen(0, function(data, ip, port)
    return "got:" .. data .. "@" .. port  -- port is the sender's source port
  end)

  local ws = net.WebSocketServer()
  ws:listen(0, function(message, isBinary)
    return "echo:" .. message
  end)

  -- HTTP client against the HTTP mock
  net.HTTPClient():request("http://127.0.0.1:" .. http.port .. "/hello", {
    options = { method = "POST", data = "flua" },
    success = function(resp)
      assertEq(resp.status, 200, "http status")
      assertEq(resp.data, "Hello flua", "http body")
      assertEq(resp.headers["X-Mock"], "1", "http header")
      done()
    end,
    error = function(err) failures = failures + 1; print("FAIL: http " .. tostring(err)); done() end,
  })

  -- TCP client against the TCP mock
  local tcpClient = net.TCPSocket({ timeout = 5000 })
  tcpClient:connect("127.0.0.1", tcp.port, {
    success = function()
      tcpClient:send("hello", {
        success = function()
          tcpClient:read({
            success = function(data)
              assertEq(data, "HELLO", "tcp reply")
              tcpClient:close()
              done()
            end,
            error = function(err) failures = failures + 1; print("FAIL: tcp read " .. tostring(err)); done() end,
          })
        end,
        error = function(err) failures = failures + 1; print("FAIL: tcp send " .. tostring(err)); done() end,
      })
    end,
    error = function(err) failures = failures + 1; print("FAIL: tcp connect " .. tostring(err)); done() end,
  })

  -- UDP client against the UDP mock
  local udpClient = net.UDPSocket({ timeout = 5000 })
  udpClient:sendTo("ping", "127.0.0.1", udp.port, {
    success = function()
      udpClient:receive({
        success = function(data)
          assertEq(string.sub(data, 1, 9), "got:ping@", "udp reply (sender's port echoed)")
          udpClient:close()
          done()
        end,
        error = function(err) failures = failures + 1; print("FAIL: udp receive " .. tostring(err)); done() end,
      })
    end,
    error = function(err) failures = failures + 1; print("FAIL: udp send " .. tostring(err)); done() end,
  })

  -- WebSocket client against the WS mock
  local wsClient = net.WebSocketClient({ timeout = 5000 })
  wsClient:addEventListener("connected", function()
    wsClient:send("hi")
  end)
  wsClient:addEventListener("dataReceived", function(data)
    assertEq(data, "echo:hi", "ws reply")
    wsClient:close()
    done()
  end)
  wsClient:addEventListener("error", function(err)
    failures = failures + 1; print("FAIL: ws " .. tostring(err)); done()
  end)
  wsClient:connect("ws://127.0.0.1:" .. ws.port)
end
