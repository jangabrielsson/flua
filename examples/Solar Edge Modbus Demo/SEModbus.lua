-- SolarEdgeModbus.lua
-- Universal read-only SolarEdge SunSpec / Modbus TCP reader for Fibaro HC3.
-- No cloud or application-specific dependencies.
--
-- API: SolarEdgeModbus.read(ip, port, callback)
--      callback(data, nil) for at least one valid measurement,
--      callback(nil, error) if the connection/protocol fails completely.
-- The callback is asynchronous; concurrent calls are rejected.
--
-- UNITS: W (powers), % (SOC), kWh (energy counters).
-- grid:    positive = exported to grid; negative = imported from grid.
-- battery: positive = charging; negative = discharging.
-- consumption = max(0, inverterAC - grid) only for an Export/Import meter.
-- pvEstimate  = max(0, inverterAC + battery); AC-equivalent ESTIMATE,
--               not a direct PV measurement (conversion losses omitted).
-- Missing/unsupported measurements are absent (nil), never forced to zero.
-- Consult data.warnings for unavailable models, registers or partial reads.
--
-- Sources: SolarEdge SunSpec Logging Technical Note v3.3 (base-0 addresses),
--          plus the optional StorEdge battery register map (not SunSpec).
-- SunSpec models are walked by DID/length, not presumed at fixed offsets.
-- StorEdge battery registers remain vendor-specific fixed addresses.

SolarEdgeModbus = {}

local busy = false
local TIMEOUT = 6000
local UNIT_ID = 1
local MAX_MODELS = 24

local function s16(v)
    if v == nil or v == 0x8000 then return nil end
    return v >= 0x8000 and v - 0x10000 or v
end

local function u32(w, address)
    local hi, lo = w[address], w[address + 1]
    if hi == nil or lo == nil or (hi == 0xFFFF and lo == 0xFFFF) then return nil end
    return hi * 65536 + lo
end

local function scaled(w, address, sfAddress, kind)
    local sf = s16(w[sfAddress])
    if sf == nil or sf < -10 or sf > 10 then return nil end
    local value
    if kind == "u32" then
        value = u32(w, address)
    elseif kind == "s16" then
        value = s16(w[address])
    end
    if value == nil then return nil end
    return value * 10 ^ sf
end

local function ascii(w, start, count)
    local result = {}
    for i = start, start + count - 1 do
        local x = w[i]
        if x == nil then return nil end
        result[#result + 1] = string.char(math.floor(x / 256), x % 256)
    end
    return table.concat(result):gsub("%z.*", ""):gsub("^%s+", ""):gsub("%s+$", "")
end

local function floatWords(w, address)
    local low, high = w[address], w[address + 1]
    if low == nil or high == nil or (low == 0xFFFF and high == 0xFFFF) then return nil end
    local value = string.unpack(">f", string.pack(">I2I2", high, low))
    if value ~= value or value == math.huge or value == -math.huge then return nil end
    return value
end

local function isExportImport(mode)
    if type(mode) ~= "string" then return false end
    return mode:lower():gsub("[^%a]", "") == "exportimport"
end

function SolarEdgeModbus.read(ip, port, callback)
    assert(type(callback) == "function", "SolarEdgeModbus: callback required")
    if busy then
        callback(nil, "SolarEdgeModbus: previous read still in progress")
        return false
    end
    if type(ip) ~= "string" or ip == "" or type(port) ~= "number" or
       port % 1 ~= 0 or port < 1 or port > 65535 then
        callback(nil, "SolarEdgeModbus: invalid IP address or port")
        return false
    end

    busy = true
    local output = { warnings = {} }
    local tasks = {}
    local index, txid, generation, models = 0, 0, 0, 0
    local done, socket = false, nil
    local lastMeterCommon = nil
    local inverterFound, meterFound = false, false

    local function warn(message)
        output.warnings[#output.warnings + 1] = message
    end

    local function useful()
        for _, name in ipairs({
            "inverterAC", "inverterDC", "inverterEnergyKWh", "grid",
            "gridImportedEnergyKWh", "gridExportedEnergyKWh", "battery", "batterySOC"
        }) do
            if output[name] ~= nil then return true end
        end
        return false
    end

    local function closeSocket()
        generation = generation + 1 -- invalidate late callbacks
        local old = socket
        socket = nil
        if old then pcall(function() old:close() end) end
    end

    local function finish(err)
        if done then return end
        done = true
        closeSocket()
        busy = false

        if not err and not useful() then
            err = "No usable measurements from this SunSpec device"
        end
        if err then
            callback(nil, err)
            return
        end

        output.timestamp = os.time()
        if output.inverterAC ~= nil and output.grid ~= nil then
            output.consumption = math.max(0, output.inverterAC - output.grid)
        end
        if output.inverterAC ~= nil and output.battery ~= nil then
            -- Estimated PV power, W (inverter AC plus battery charging power).
            -- Approximate: does not account precisely for conversion losses.
            output.pvEstimate = math.max(0, output.inverterAC + output.battery)
        end
        if not inverterFound then warn("SunSpec inverter model 101/102/103 not found") end
        if not meterFound then warn("Export/Import meter not detected; grid unavailable") end
        callback(output, nil)
    end

    local function add(address, count, name, handler, critical, condition)
        tasks[#tasks + 1] = {
            address = address, count = count, name = name,
            handler = handler, critical = critical, condition = condition
        }
    end

    local function insertNext(address, count, name, handler)
        table.insert(tasks, index + 1, {
            address = address, count = count, name = name,
            handler = handler, critical = false
        })
    end

    local scan -- forward declaration; discovery actions add later measurement tasks
    scan = function(address)
        if address < 40002 or address > 65533 or models >= MAX_MODELS then
            warn("SunSpec discovery limit reached at " .. tostring(address))
            return
        end
        insertNext(address, 2, "model header " .. address, function(w)
            local did, length = w[address], w[address + 1]
            if did == 0xFFFF then return end -- standard end marker
            if did == nil or length == nil or length == 0 or length == 0xFFFF or
               length > 1024 or address + 2 + length > 65535 then
                warn("Invalid SunSpec model header at " .. address)
                return
            end

            models = models + 1
            if did == 1 then
                -- First DID=1 is the Common block at 40002.
                -- Later DID=1 blocks describe individual SolarEdge meters.
                if address ~= 40002 then
                    local meter = { common = address, mode = nil }
                    lastMeterCommon = meter
                    if length >= 42 then
                        add(address + 34, 8, "meter options " .. address, function(words)
                            meter.mode = ascii(words, address + 34, 8)
                            if not meter.mode or meter.mode == "" then
                                warn("Meter type unavailable at " .. address)
                            end
                        end)
                    else
                        warn("Meter common block too short at " .. address)
                    end
                end
            elseif did == 101 or did == 102 or did == 103 then
                if not inverterFound then
                    inverterFound = true
                    if length >= 15 then
                        add(address + 14, 2, "inverter AC power", function(words)
                            output.inverterAC = scaled(words, address + 14, address + 15, "s16")
                            if output.inverterAC == nil then warn("Inverter AC power not implemented") end
                        end)
                    end
                    if length >= 27 then
                        add(address + 24, 3, "inverter energy", function(words)
                            local value = scaled(words, address + 24, address + 26, "u32")
                            output.inverterEnergyKWh = value and value / 1000 or nil
                            if value == nil then warn("Inverter energy counter not implemented") end
                        end)
                    end
                    if length >= 33 then
                        add(address + 31, 2, "inverter DC power", function(words)
                            output.inverterDC = scaled(words, address + 31, address + 32, "s16")
                            if output.inverterDC == nil then warn("Inverter DC power not implemented") end
                        end)
                    end
                end
                lastMeterCommon = nil
            elseif did >= 201 and did <= 204 then
                local meter = lastMeterCommon
                lastMeterCommon = nil
                if meter then
                    local function selected()
                        if not isExportImport(meter.mode) then return false end
                        if meterFound then return false end
                        meterFound = true
                        output.meterMode = meter.mode
                        return true
                    end
                    -- Once the model is found, read only a verified E+I meter.
                    -- The common block options task runs before these tasks.
                    local function wanted()
                        if meter.selected == nil then meter.selected = selected() end
                        return meter.selected
                    end
                    if length >= 23 then
                        add(address + 18, 5, "grid power", function(words)
                            output.grid = scaled(words, address + 18, address + 22, "s16")
                            if output.grid == nil then warn("Grid power not implemented") end
                        end, false, wanted)
                    end
                    if length >= 55 then
                        -- Read each energy counter separately: an unsupported
                        -- field must not suppress the other counter.
                        local sfAddress = address + 54
                        add(sfAddress, 1, "meter energy scale", function(words)
                            local sf = s16(words[sfAddress])
                            if sf and sf >= -10 and sf <= 10 then
                                meter.energySF = sf
                            else
                                warn("Meter energy scale unavailable")
                            end
                        end, false, wanted)
                        add(address + 38, 2, "exported energy", function(words)
                            local value = u32(words, address + 38)
                            if value ~= nil and meter.energySF ~= nil then
                                output.gridExportedEnergyKWh =
                                    value * 10 ^ meter.energySF / 1000
                            else
                                warn("Exported energy counter unavailable")
                            end
                        end, false, wanted)
                        add(address + 46, 2, "imported energy", function(words)
                            local value = u32(words, address + 46)
                            if value ~= nil and meter.energySF ~= nil then
                                output.gridImportedEnergyKWh =
                                    value * 10 ^ meter.energySF / 1000
                            else
                                warn("Imported energy counter unavailable")
                            end
                        end, false, wanted)
                    end
                    if length < 23 then warn("Meter model too short at " .. address) end
                else
                    warn("Meter model without common block at " .. address)
                end
            else
                lastMeterCommon = nil -- avoid associating an unrelated model
            end

            scan(address + 2 + length)
        end)
    end

    -- Identify SunSpec before consulting any model-specific registers.
    add(40000, 4, "SunSpec signature", function(w)
        if ascii(w, 40000, 2) ~= "SunS" or w[40002] ~= 1 or
           w[40003] == nil or w[40003] == 0 or w[40003] > 1024 then
            return "Invalid SunSpec signature or common model"
        end
        scan(40002 + 2 + w[40003])
    end, true)

    -- Vendor-specific StorEdge battery registers, independent of the
    -- standard SunSpec model chain. Unsupported models may reject them.
    add(57716, 2, "battery power", function(w)
        local raw = floatWords(w, 57716)
        if raw and math.abs(raw) <= 100000 then
            output.battery = raw -- + charge, - discharge
        else
            warn("Battery power unavailable or invalid")
        end
    end)
    add(57732, 2, "battery SOC", function(w)
        local soc = floatWords(w, 57732)
        if soc and soc >= 0 and soc <= 100 then
            output.batterySOC = soc
        else
            warn("Battery state of charge unavailable or invalid")
        end
    end)

    local nextTask
    local function connectSocket(success, failed)
        local ok, newSocket = pcall(function()
            return net.TCPSocket({ timeout = TIMEOUT })
        end)
        if not ok then failed(tostring(newSocket)) return end
        socket = newSocket
        generation = generation + 1
        local myGeneration = generation
        local function current() return not done and generation == myGeneration end
        local started, err = pcall(function()
            newSocket:connect(ip, port, {
                success = function()
                    if current() then success() end
                end,
                error = function(reason)
                    if current() then failed(tostring(reason)) end
                end
            })
        end)
        if not started and current() then failed(tostring(err)) end
    end

    local function transportFailure(task, reason)
        local message = task.name .. " (" .. task.address .. "): " .. reason
        if task.critical then finish(message) return end
        warn(message .. " - skipped; reconnecting TCP")
        closeSocket() -- old response must never be mistaken for next task
        connectSocket(function()
            nextTask()
        end, function(err)
            warn("TCP reconnect failed: " .. err)
            if useful() then finish(nil) else finish("TCP reconnect failed: " .. err) end
        end)
    end

    nextTask = function()
        if done then return end
        index = index + 1
        local task = tasks[index]
        if not task then finish(nil) return end
        if task.condition and not task.condition() then
            nextTask()
            return
        end

        txid = (txid % 65535) + 1
        local expectedTxid = txid
        local request = string.pack(">I2I2I2BBI2I2", expectedTxid, 0, 6, UNIT_ID, 3, task.address, task.count)
        local buffer = ""
        local myGeneration = generation
        local activeSocket = socket
        local function current() return not done and generation == myGeneration end

        local function consume(frame)
            local tid, protocol, length, unit, func =
                string.unpack(">I2I2I2BB", frame)
            if tid ~= expectedTxid or protocol ~= 0 or unit ~= UNIT_ID then
                finish("Invalid Modbus transaction header at " .. task.address)
                return
            end
            if func == 0x83 then
                local code = frame:byte(9)
                if task.critical then
                    finish("Modbus exception " .. tostring(code) .. " at " .. task.address)
                else
                    warn(task.name .. " (" .. task.address .. "): Modbus exception " .. tostring(code))
                    nextTask()
                end
                return
            end
            if func ~= 3 or length ~= 3 + task.count * 2 or
               frame:byte(9) ~= task.count * 2 then
                finish("Invalid Modbus payload at " .. task.address)
                return
            end
            local words = {}
            for n = 0, task.count - 1 do
                words[task.address + n] = string.unpack(">I2", frame, 10 + n * 2)
            end
            local ok, result = pcall(task.handler, words)
            if not ok then
                if task.critical then finish("Decoder error: " .. tostring(result))
                else warn(task.name .. ": decoder error: " .. tostring(result)); nextTask() end
            elseif result then
                if task.critical then finish(tostring(result))
                else warn(task.name .. ": " .. tostring(result)); nextTask() end
            else
                nextTask()
            end
        end

        local waitResponse
        waitResponse = function()
            local started, err = pcall(function()
                activeSocket:read({
                    success = function(data)
                        if not current() then return end
                        if type(data) ~= "string" or #data == 0 then
                            transportFailure(task, "empty TCP response")
                            return
                        end
                        buffer = buffer .. data
                        if #buffer >= 6 then
                            local length = buffer:byte(5) * 256 + buffer:byte(6)
                            if length < 3 or length > 253 then
                                finish("Invalid Modbus frame length at " .. task.address)
                                return
                            end
                            if #buffer >= 6 + length then
                                consume(buffer:sub(1, 6 + length))
                                return
                            end
                        end
                        waitResponse()
                    end,
                    error = function(errMsg)
                        if current() then transportFailure(task, "TCP read: " .. tostring(errMsg)) end
                    end
                })
            end)
            if not started and current() then
                transportFailure(task, "TCP read: " .. tostring(err))
            end
        end

        local started, err = pcall(function()
            activeSocket:write(request, {
                success = function()
                    if current() then waitResponse() end
                end,
                error = function(errMsg)
                    if current() then transportFailure(task, "TCP write: " .. tostring(errMsg)) end
                end
            })
        end)
        if not started and current() then
            transportFailure(task, "TCP write: " .. tostring(err))
        end
    end

    connectSocket(nextTask, function(err)
        finish("TCP connect: " .. tostring(err))
    end)
    return true
end
