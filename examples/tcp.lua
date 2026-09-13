--%%name:tcp-demo
-- Example: net.TCPSocket — the HC3-style asynchronous TCP client.
-- Run with:
--   .venv/bin/flua examples/tcp.lua
--
-- Start a local echo service first, e.g.:
--   nc -l 7777              (macOS)
--   ncat -l 7777 --keep-open  (Linux)
-- Then type a reply in that terminal — the example sends a line and reads
-- one back.
local HOST, PORT = "127.0.0.1", 7777

setTimeout(function()
  local sock = net.TCPSocket({ timeout = 8000 })  -- ms
  sock:connect(HOST, PORT, {
    success = function()
      print("connected to", HOST, PORT)
      sock:send("ping from flua\n", {
        success = function()
          sock:readUntil("\n", {
            success = function(data)
              print("echo:", data)
              sock:close()
            end,
            error = function(err) print("read error:", err) end,
          })
        end,
        error = function(err) print("send error:", err) end,
      })
    end,
    error = function(err)
      print("connect failed:", err)
      print("start an echo service first: nc -l 7777")
    end,
  })
end, 100)
