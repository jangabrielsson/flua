--%%name:HvacSystemAuto
--%%type:com.fibaro.hvacSystemAuto

-- Thermostat auto should handle actions: setThermostatMode, setCoolingThermostatSetpoint, setHeatingThermostatSetpoint
-- Proeprties that should be updated:
-- * supportedThermostatModes - array of modes supported by the thermostat eg. {"Auto", "Off", "Heat", "Cool"}
-- * thermostatMode - current mode of the thermostat
-- * coolingThermostatSetpoint - set point for cooling, supported units: "C" - Celsius, "F" - Fahrenheit
-- * heatingThermostatSetpoint - set point for heating, supported units: "C" - Celsius, "F" - Fahrenheit
-- * hysteresis - the Auto-mode deadband half-width the default view's
--   +/- buttons and slider offset each setpoint by (default 1)

-- handle action for mode change 
function QuickApp:setThermostatMode(mode)
    print("Setting thermostat mode to: " .. mode)
    self:updateProperty("thermostatMode", mode)
end

-- handle action for setting set point for cooling
function QuickApp:setCoolingThermostatSetpoint(value, unit)
    print("Setting cooling setpoint to: " .. value .. " " .. (unit or "C"))
    self:updateProperty("coolingThermostatSetpoint", { value= value, unit= unit or "C" })
end

-- handle action for setting set point for heating
function QuickApp:setHeatingThermostatSetpoint(value, unit)
    print("Setting heating setpoint to: " .. value .. " " .. (unit or "C"))
    self:updateProperty("heatingThermostatSetpoint", { value= value, unit= unit or "C" })
end

function QuickApp:onInit()
    self:debug("onInit")

    -- set supported modes for thermostat
    self:updateProperty("supportedThermostatModes", {"Auto", "Off", "Heat", "Cool"})

    -- setup default values
    self:updateProperty("thermostatMode", "Auto")
    self:updateProperty("hysteresis", 1)  -- the Auto deadband half-width
    self:setCoolingThermostatSetpoint(23)
    self:setHeatingThermostatSetpoint(20)
end
