--%%name:HvacSystemHeat
--%%type:com.fibaro.hvacSystemHeat

-- Thermostat heat should handle actions: setThermostatMode, setHeatingThermostatSetpoint
-- Proeprties that should be updated:
-- * supportedThermostatModes - array of modes supported by the thermostat eg. {"Off", "Heat"}
-- * thermostatMode - current mode of the thermostat
-- * heatingThermostatSetpoint - set point for heating, supported units: "C" - Celsius, "F" - Fahrenheit

-- handle action for mode change 
function QuickApp:setThermostatMode(mode)
    self:updateProperty("thermostatMode", mode)
end

-- handle action for setting set point for heating
function QuickApp:setHeatingThermostatSetpoint(value, unit)
    self:updateProperty("heatingThermostatSetpoint", { value= value, unit= unit or "C" })
end

function QuickApp:onInit()
    self:debug("onInit")

    -- set supported modes for thermostat
    self:updateProperty("supportedThermostatModes", {"Off", "Heat"})

    -- setup default values
    self:updateProperty("thermostatMode", "Heat")
    self:setHeatingThermostatSetpoint(20)
end
