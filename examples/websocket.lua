--%%name:ws-demo
-- Example: net.WebSocketClient — the HC3-style WebSocket client (firmware
-- 5.041+ API). Run with:
--   .venv/bin/flua examples/websocket.lua
--
-- Targets the public echo server at wss://echo.websocket.org (the URL from
-- the Fibaro manual); if it is down, the error event prints cleanly.
setTimeout(function()
  local ws = net.WebSocketClientTls({ timeout = 5000 })  -- ms

  ws:addEventListener("connected", function()
    print("connected:", ws:isOpen())
    ws:send("hello from flua")
  end)

  ws:addEventListener("dataReceived", function(data)
    print("echo:", data)
    ws:close()
  end)

  ws:addEventListener("disconnected", function()
    print("disconnected")
  end)

  ws:addEventListener("error", function(err)
    print("ws error:", err)
  end)

  ws:connect("wss://echo.websocket.org")
end, 100)
