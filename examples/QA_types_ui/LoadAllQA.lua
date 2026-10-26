--%%name:LoadAllQA
--%%type:com.fibaro.deviceController

function QuickApp:onInit()
    self:debug(self.name,self.id)
    _FLUA.loadQAfromFile("examples/QA_types_ui/AlarmPartition.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/BinarySensor.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/BinarySwitch.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/MultilevelSensor.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/MultilevelSwitch.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/BaseShutter.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/RollerShutter.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/HvacSystemHeat.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/HvacSystemAuto.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/HvacSystemCool.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/Player.lua")
    _FLUA.loadQAfromFile("examples/QA_types_ui/LightSensor.lua")
end