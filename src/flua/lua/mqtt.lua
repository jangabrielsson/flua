-- mqtt.*: MQTT 3.1.1 client for QAs — the HC3's documented API.
--
--   local client = mqtt.Client.connect("mqtt://broker:1883", {
--     clientId = "my-qa", keepAlivePeriod = 60, cleanSession = true,
--     username = "...", password = "...",
--     lastWill = { topic = "qa/status", payload = "offline", qos = mqtt.QoS.AT_LEAST_ONCE, retain = true },
--     callback = function(errorCode) ... end,   -- connect completion (not broker ack)
--   })
--   client:addEventListener("connected", function(e) ... e.sessionPresent, e.returnCode ... end)
--   client:addEventListener("message", function(e) ... e.topic, e.payload, e.qos, e.retain, e.packetId, e.dup ... end)
--   client:subscribe("lights/#", { qos = mqtt.QoS.EXACTLY_ONCE })   -- returns packetId
--   client:publish("lights/1", "ON", { qos = 1, retain = true })    -- returns packetId
--   client:unsubscribe("lights/#")                                   -- returns packetId
--   client:disconnect()   client:isConnected()
--
-- Ops run in Python worker threads; events arrive through the pump and
-- fire addEventListener callbacks in this QA's environment. Per-op
-- callbacks (options.callback) fire when the operation completes with an
-- errorCode (0 = success) — they do NOT wait for broker acks; the
-- subscribed/unsubscribed/published events do.
local qaId = _FLUA.qaId

local clients = {}  -- conn -> client instance
local nextPacketId = 0

local function allocPacketId()
  nextPacketId = nextPacketId % 65535 + 1
  return nextPacketId
end

mqtt = {
  QoS = { AT_MOST_ONCE = 0, AT_LEAST_ONCE = 1, EXACTLY_ONCE = 2 },
  MQTTConnectReturnCode = {
    [0] = "Connection Accepted",
    [1] = "Unacceptable Protocol Version",
    [2] = "Identifier Rejected",
    [3] = "Server Unavailable",
    [4] = "Bad Username or Password",
    [5] = "Not Authorized",
  },
}

local MqttClient = {}
mqtt.Client = MqttClient
MqttClient.__index = MqttClient

local function newClient()
  local client = setmetatable(
    { _conn = nil, _listeners = {}, _opCb = {}, _connected = false },
    MqttClient
  )
  client._conn = _PY.mqtt_new(qaId)
  clients[client._conn] = client
  return client
end

-- options.callback is a function: strip it before crossing the bridge
local function wireOptions(options)
  local t = {}
  if options then
    for k, v in pairs(options) do
      if k ~= "callback" then t[k] = v end
    end
  end
  return t
end

-- connect is a CLASS method (the HC3 docs): returns the new client.
function MqttClient.connect(uri, options)
  options = options or {}
  local client = newClient()
  client._opCb["connect"] = options.callback
  _PY.post{
    type = "mqttConnect",
    qa = qaId,
    conn = client._conn,
    uri = tostring(uri),
    options = wireOptions(options),
  }
  return client
end

function MqttClient:addEventListener(eventName, callback)
  local list = self._listeners[eventName]
  if not list then
    list = {}
    self._listeners[eventName] = list
  end
  list[#list + 1] = callback
end

function MqttClient:subscribe(topic, options)
  options = options or {}
  local defaultQos = tonumber(options.qos) or 0
  local topics = {}
  if type(topic) == "table" then
    for _, item in ipairs(topic) do
      if type(item) == "table" then
        topics[#topics + 1] = { tostring(item[1]), tonumber(item[2]) or defaultQos }
      else
        topics[#topics + 1] = { tostring(item), defaultQos }
      end
    end
  else
    topics[#topics + 1] = { tostring(topic), defaultQos }
  end
  local packetId = allocPacketId()
  self._opCb["subscribe:" .. packetId] = options.callback
  _PY.post{
    type = "mqttSubscribe",
    qa = qaId,
    conn = self._conn,
    packetId = packetId,
    topics = topics,
  }
  return packetId
end

function MqttClient:unsubscribe(topics, options)
  options = options or {}
  local list = {}
  if type(topics) == "table" then
    for _, t in ipairs(topics) do list[#list + 1] = tostring(t) end
  else
    list[1] = tostring(topics)
  end
  local packetId = allocPacketId()
  self._opCb["unsubscribe:" .. packetId] = options.callback
  _PY.post{
    type = "mqttUnsubscribe",
    qa = qaId,
    conn = self._conn,
    packetId = packetId,
    topics = list,
  }
  return packetId
end

function MqttClient:publish(topic, payload, options)
  options = options or {}
  local packetId = allocPacketId()
  self._opCb["publish:" .. packetId] = options.callback
  _PY.post{
    type = "mqttPublish",
    qa = qaId,
    conn = self._conn,
    packetId = packetId,
    topic = tostring(topic),
    payload = tostring(payload),
    qos = tonumber(options.qos) or 0,
    retain = not not options.retain,
  }
  return packetId
end

function MqttClient:disconnect(options)
  options = options or {}
  self._opCb["disconnect"] = options.callback
  _PY.post{ type = "mqttDisconnect", qa = qaId, conn = self._conn }
end

function MqttClient:isConnected()
  return self._connected
end

-- ------------------------------------------------------------------ dispatch
local kindMap = {
  mqttSubscribe = "subscribe",
  mqttUnsubscribe = "unsubscribe",
  mqttPublish = "publish",
  mqttDisconnect = "disconnect",
}

local function callbackErr(err)
  print("[mqtt] callback error: " .. tostring(err))
end

local function handleMqttEvent(msg)
  local client = clients[msg.conn]
  if not client then return end
  local event = msg.event
  local data = msg.data or {}
  if event == "connectDone" then
    local cb = client._opCb["connect"]
    client._opCb["connect"] = nil
    if cb then xpcall(function() cb(data.code or 0) end, callbackErr) end
    return
  end
  if event == "opDone" then
    local key = (kindMap[data.kind] or data.kind or "") .. ":" .. tostring(data.packetId or "")
    local cb = client._opCb[key]
    client._opCb[key] = nil
    if cb then xpcall(function() cb(data.code or 0) end, callbackErr) end
    return
  end
  if event == "connected" then
    client._connected = true
  elseif event == "closed" or event == "error" then
    client._connected = false
  end
  local list = client._listeners[event]
  if not list then return end
  for _, fn in ipairs(list) do
    xpcall(function() fn(data) end, callbackErr)
  end
end

-- one handler per QA; the shared dispatch (init.lua) routes by qa
_FLUA.mqttHandlers[qaId] = handleMqttEvent
