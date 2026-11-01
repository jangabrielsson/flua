--%%name:SimDevices
--%%type:com.fibaro.genericDevice
--%%description:"Simulated devices bundled with flua"

local devices = {
  "alarmPartition",
  "binarySensor",
  "binarySwitch",
  "coDetector",
  "colorController",
  "deviceController",
  "doorSensor",
  "energyMeter",
  "fireDetector",
  "floodSensor",
  "genericDevice",
  "heatDetector",
  "humiditySensor",
  "hvacSystemAuto",
  "hvacSystemCool",
  "hvacSystemHeat",
  "lightSensor",
  "motionSensor",
  "multilevelSensor",
  "multilevelSwitch",
  "player",
  "powerMeter",
  "rainDetector",
  "rainSensor",
  "remoteController",
  "smokeSensor",
  "temperatureSensor",
  "weather",
  "windowSensor",
  "windSensor",
  "weatherMgr"
}
function QuickApp:onInit()
  self:debug("sim devices ready, id", self.id)
  -- simulated devices stay up for the whole run (a drained QA stops answering)
  for _,d in ipairs(devices) do 
    _FLUA.loadSimDevice(d)
  end
end