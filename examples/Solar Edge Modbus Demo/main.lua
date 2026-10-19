-- Author: https://forum.fibaro.com/profile/63815-łukasz997 

--%%name:Solar Edge Modbus Demo
--%%type:com.fibaro.genericDevice
--%%property:useUiView=true
--%%property:typeTemplateInitialized=true
--%%property:userDescription=
--%%file:SEModbus.lua,SEModbus
-- --------------- EOH ---------------
-- SolarEdgeModbus_Demo.lua
-- Fibaro HC3 QuickApp demo: formatted SolarEdge Modbus TCP readings.
-- Add SolarEdgeModbus.lua as a separate QuickApp Lua file.
-- Adjust IP and port below. This demo reads once at startup.
-- To read again, call the QuickApp action refreshSolarEdge.
--
-- SIGN CONVENTION:
--   grid    > 0: power exported to grid; < 0: power imported from grid
--   battery > 0: charging the battery; < 0: discharging the battery
-- All instantaneous powers in W. Energy counters in kWh.

--%%name=Solar Edge Modbus Demo
--%%type=com.fibaro.genericDevice

--%%file=dev/SolarEdge/SolarEdgeModbus1.lua,SEModbus

if require then require("solar_modbus_mock") end

local SOLAREDGE_IP = "127.0.0.1" -- Change to your inverter's LAN IP
local SOLAREDGE_PORT = 1502

local function fmtNumber(value, unit, decimals, signed)
    if type(value) ~= "number" then return "N/A" end
    local pattern = signed and ("%+." .. decimals .. "f") or ("%." .. decimals .. "f")
    return string.format(pattern, value) .. " " .. unit
end

local function fmtText(value)
    if value == nil then return "N/A" end
    return tostring(value)
end

local function addRow(lines, name, value, description)
    lines[#lines + 1] = string.format("%-26s %14s  %s", name, value, description)
end

local function formattedReport(data, host, port)
    local lines = {
        "",
        "SOLAREDGE - LIVE MODBUS TCP READINGS",
        string.rep("=", 86),
        "Inverter: " .. host .. ":" .. port,
        "Read time: " .. (data.timestamp and os.date("%Y-%m-%d %H:%M:%S", data.timestamp) or "N/A"),
        "",
        string.format("%-26s %14s  %s", "FIELD", "VALUE", "MEANING"),
        string.rep("-", 86)
    }

    addRow(lines, "pvEstimate", fmtNumber(data.pvEstimate, "W", 1),
           "Estimated PV production (not a direct PV measurement)")
    addRow(lines, "inverterAC", fmtNumber(data.inverterAC, "W", 1),
           "Power reported at the inverter AC output")
    addRow(lines, "inverterDC", fmtNumber(data.inverterDC, "W", 1),
           "DC power reported by inverter (may include battery)")
    addRow(lines, "consumption", fmtNumber(data.consumption, "W", 1),
           "Calculated home load (inverter AC minus grid exchange)")
    addRow(lines, "grid", fmtNumber(data.grid, "W", 1, true),
           "Grid exchange: + export, - import")
    addRow(lines, "battery", fmtNumber(data.battery, "W", 1, true),
           "Battery exchange: + charging, - discharging")
    addRow(lines, "batterySOC", fmtNumber(data.batterySOC, "%", 1),
           "Battery state of charge")
    addRow(lines, "inverterEnergyKWh", fmtNumber(data.inverterEnergyKWh, "kWh", 3),
           "Cumulative AC energy reported by inverter (not PV-only)")
    addRow(lines, "gridImportedEnergyKWh", fmtNumber(data.gridImportedEnergyKWh, "kWh", 3),
           "Cumulative energy imported from grid")
    addRow(lines, "gridExportedEnergyKWh", fmtNumber(data.gridExportedEnergyKWh, "kWh", 3),
           "Cumulative energy exported to grid")
    addRow(lines, "meterMode", fmtText(data.meterMode),
           "Meter configuration reported by inverter")

    lines[#lines + 1] = string.rep("-", 86)
    lines[#lines + 1] = "NOTES: pvEstimate = max(0, inverterAC + battery)."
    lines[#lines + 1] = "       consumption = max(0, inverterAC - grid)."
    lines[#lines + 1] = "       Estimated values may differ from cloud monitoring."

    if data.warnings and #data.warnings > 0 then
        lines[#lines + 1] = "WARNINGS:"
        for _, warning in ipairs(data.warnings) do
            lines[#lines + 1] = "  - " .. tostring(warning)
        end
    else
        lines[#lines + 1] = "Warnings: none"
    end
    lines[#lines + 1] = string.rep("=", 86)

    -- Return individual lines: Fibaro HC3 debug log does not preserve embedded newlines.
    return lines
end

function QuickApp:refreshSolarEdge()
    self:debug("SolarEdge: connecting to " .. SOLAREDGE_IP .. ":" .. SOLAREDGE_PORT .. " ...")
    SolarEdgeModbus.read(SOLAREDGE_IP, SOLAREDGE_PORT, function(data, err)
        if err then
            self:error("SolarEdge: Modbus read failed: " .. tostring(err))
            return
        end
        for _, line in ipairs(formattedReport(data, SOLAREDGE_IP, SOLAREDGE_PORT)) do
            if line ~= "" then self:debug(line) end
        end
    end)
end

function QuickApp:onInit()
    self:debug("SolarEdge Modbus TCP demo started (one-time read).")
    self:refreshSolarEdge()
end
