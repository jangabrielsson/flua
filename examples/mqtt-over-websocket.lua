--%%name:MQTT over WebSocket
--%%type:com.fibaro.deviceController
-- Example: MQTT over WebSocket, built in Lua on top of net.WebSocketClient —
-- the pattern from Fibaro's 5.221 BETA documentation, so QA code written
-- for the HC3 runs identically under flua.
--
-- Run with:
--   BROKER_URL=ws://127.0.0.1:8080/mqtt .venv/bin/flua examples/mqtt-over-websocket.lua
--
-- The QA connects with the mqtt subprotocol, sends an MQTT 3.1.1 CONNECT
-- via sendBinary, accumulates received bytes (one WebSocket frame is NOT
-- one MQTT packet), answers a CONNACK with a SUBSCRIBE, and disconnects on
-- the SUBACK. Without a broker the connect fails, the error event fires,
-- and the QA exits cleanly — the example always terminates.

local broker = os.getenv("BROKER_URL") or "ws://127.0.0.1:8080/mqtt"
local clientId = "flua-demo-" .. tostring(os.time())

-- Remaining Length: 7 payload bits per byte, MSB set while more bytes follow.
local function varint(n)
  local out = {}
  repeat
    local byte = n % 128
    n = n // 128
    if n > 0 then byte = byte + 128 end
    out[#out + 1] = string.char(byte)
  until n == 0
  return table.concat(out)
end

-- MQTT string field: 2 byte big-endian length, then the raw bytes.
local function mqttString(text)
  return string.char(#text // 256, #text % 256) .. text
end

-- MQTT 3.1.1 CONNECT: clean session, the keep-alive, and the client id.
local function connectPacket(keepAlive)
  local variableHeader = mqttString("MQTT")          -- protocol name
      .. string.char(0x04)                           -- protocol level 4
      .. string.char(0x02)                           -- connect flags: clean session
      .. string.char(keepAlive // 256, keepAlive % 256)
  local body = variableHeader .. mqttString(clientId)
  return string.char(0x10) .. varint(#body) .. body  -- 0x10 = CONNECT
end

-- SUBSCRIBE (QoS 1) to one topic at QoS 0.
local function subscribePacket(packetId, topic)
  local body = string.char(packetId // 256, packetId % 256)
      .. mqttString(topic) .. string.char(0x00)
  return string.char(0x82) .. varint(#body) .. body  -- 0x82 = SUBSCRIBE
end

local DISCONNECT = string.char(0xE0, 0x00)

-- Peel one whole MQTT packet off the buffer; nil when it is incomplete.
local function mqttPacket(buffer)
  if #buffer < 2 then return nil end
  local multiplier, value, i = 1, 0, 2
  while true do
    local byte = string.byte(buffer, i)
    if not byte then return nil end
    value = value + (byte % 128) * multiplier
    i = i + 1
    if byte < 128 then break end
    multiplier = multiplier * 128
  end
  local total = i - 1 + value
  if #buffer < total then return nil end
  return buffer:sub(1, total), buffer:sub(total + 1)
end

function QuickApp:onInit()
  self.buffer = ""
  self.finished = false
  -- a safety leash: a silent broker must not hang the run
  setTimeout(function() self:finish("no broker response") end, 10000)

  self.sock = net.WebSocketClient({ timeout = 5000 })
  self.sock:addEventListener("connected", function()
    self:debug("connected — sending MQTT CONNECT")
    self.sock:sendBinary(connectPacket(30))
  end)
  self.sock:addEventListener("dataReceived", function(payload, isBinary)
    if not isBinary then return end  -- MQTT mandates binary frames
    self.buffer = self.buffer .. payload
    self:handlePackets()
  end)
  self.sock:addEventListener("error", function(err)
    self:debug("ws error:", err)
    self:finish()
  end)
  self.sock:addEventListener("disconnected", function()
    self:debug("disconnected")
    self:finish()
  end)
  self:debug("connecting to", broker)
  self.sock:connect(broker, { ["Sec-WebSocket-Protocol"] = "mqtt" })
end

function QuickApp:handlePackets()
  while true do
    local packet, rest = mqttPacket(self.buffer)
    if not packet then break end
    self.buffer = rest
    local kind = string.byte(packet, 1) // 16  -- the packet type nibble
    if kind == 0x2 then
      self:debug("CONNACK received — subscribing")
      self.sock:sendBinary(subscribePacket(1, "flua/demo"))
    elseif kind == 0x9 then
      self:debug("SUBACK received — MQTT over WebSocket works")
      self.sock:sendBinary(DISCONNECT)
      self.sock:close()
    elseif kind == 0x3 then
      self:debug("PUBLISH received")
    elseif kind == 0xD then
      self:debug("PINGRESP received")
    end
  end
end

function QuickApp:finish(reason)
  if self.finished then return end
  self.finished = true
  self:debug("done" .. (reason and (" — " .. reason) or ""))
  exit(0)
end
