--%%name:mqtt-demo
-- Example: mqtt.* — the HC3's MQTT client (firmware 5.030+ API).
-- Run with:
--   .venv/bin/flua examples/mqtt.lua
--
-- Connects to the public broker at broker.hivemq.com, subscribes to a
-- topic, publishes a message and reads its own echo. If the broker is
-- unreachable, the error path prints cleanly.
setTimeout(function()
  local client = mqtt.Client.connect("mqtt://broker.hivemq.com:1883", {
    clientId = "flua-demo-" .. tostring(os.time()),
    cleanSession = true,
    callback = function(errorCode)
      print("connect result:", errorCode == 0 and "ok" or "failed " .. tostring(errorCode))
    end,
  })

  client:addEventListener("connected", function()
    print("connected:", client:isConnected())
    client:subscribe("flua/demo", { qos = mqtt.QoS.AT_LEAST_ONCE })
  end)

  client:addEventListener("subscribed", function(event)
    print("subscribed:", event.packetId, json.encode(event.results))
    client:publish("flua/demo", "hello from flua", {
      qos = mqtt.QoS.AT_LEAST_ONCE,
      retain = false,
    })
  end)

  client:addEventListener("message", function(event)
    print("mqtt echo:", event.topic, event.payload, "qos=" .. tostring(event.qos))
    client:disconnect()
  end)

  client:addEventListener("closed", function()
    print("closed")
  end)

  client:addEventListener("error", function(event)
    print("mqtt error:", event.code)
  end)
end, 100)
