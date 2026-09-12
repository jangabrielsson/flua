--%%name:udp-demo
-- Example: net.UDPSocket — the HC3-style asynchronous UDP datagram socket.
-- Run with:
--   .venv/bin/flua examples/udp.lua
--
-- Sends the manual's broadcast example datagram to port 44444, then waits
-- briefly for a reply. To see the datagram:
--   nc -u -l 44444
setTimeout(function()
  local udp = net.UDPSocket({ broadcast = true, timeout = 1000 })  -- ms
  local payload = string.char(0x46, 0x49, 0x42, 0x41, 0x52, 0x4f)  -- "FIBARO"
  udp:sendTo(payload, "255.255.255.255", 44444, {
    success = function()
      print("sent broadcast to 255.255.255.255:44444")
      udp:receive({
        success = function(data) print("reply:", data) end,
        error = function(e) print("no reply (", e, ") — that's fine") end,
      })
    end,
    error = function(e) print("send error:", e) end,
  })
end, 100)
