--%%name:AlarmPanel
--%%type:com.fibaro.binarySwitch
--%%u:{button="btnArm",text="Arm",onReleased="arm"}
--%%u:{button="btnDisarm",text="Disarm",onReleased="disarm"}
--%%u:{label="lblState",text="disarmed"}
-- The mock alarm panel DEPLOYED AS A QA: its UI is a real device in the
-- sim, and requiring alarm-logic makes its endpoints answer every QA's
-- api.* calls (override routes). Run it alongside consumers:
--   .venv/bin/flua --api local examples/alarm-panel.lua examples/uses-alarm-panel.lua

function QuickApp:onInit()
  local alarm = require("alarm-logic")
  alarm.exitDelayMs = 500
end

function QuickApp:arm()
  api.post("/alarms/v1/partitions/1/actions/arm")
end

function QuickApp:disarm()
  api.delete("/alarms/v1/partitions/1/actions/disarm")
end
