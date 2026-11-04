--%%name:flua_p_probe
--%%type:com.fibaro.binarySwitch
-- --------------- EOH ---------------
-- Tier-3 parity probe QA. The SAME self-test runs on the HC3 (capture) and
-- in the sim (replay): every PROBE line is deterministic — status codes,
-- types and self-set values only, never names/ids of house objects — so
-- the two /debugMessages transcripts are directly comparable.
-- Every step runs under pcall: a failing step reports an ERR line instead
-- of killing onInit, so the transcript always tells us what happened.
-- Sentinels: PROBE_DONE ends onInit; the timer line comes last; then the
-- QA has no pending work (it exits in the sim; the capture deletes it).
--
-- Built on dev/apitest.lua's spirit (a systematic self-test over the
-- endpoint surface, logged via self:debug), stripped to the house-
-- independent, dual-runnable core.

function QuickApp:onInit()
  local function report(label, value)
    -- single pre-joined argument: the HC3 and the sim must format multi-arg
    -- debug lines the same way — a single string removes the risk
    self:debug("PROBE " .. label .. " -> " .. tostring(value))
  end

  local function probe(label, fn)
    local ok, value = pcall(fn)
    if ok then
      report(label, value)
    else
      report(label, "ERR " .. tostring(value))
    end
  end

  local function getStatus(path)
    local _, status = api.get(path)
    return status
  end

  -- the read surface, status-only (house-independent)
  probe("api.get /devices", function() return getStatus("/devices") end)
  probe("api.get /plugins", function() return getStatus("/plugins") end)
  probe("api.get /globalVariables", function() return getStatus("/globalVariables") end)
  probe("api.get /settings/info", function() return getStatus("/settings/info") end)
  probe("api.get /refreshStates", function() return getStatus("/refreshStates") end)
  probe("api.get /rooms", function() return getStatus("/rooms") end)
  probe("api.get /scenes", function() return getStatus("/scenes") end)
  probe("api.get /customEvents", function() return getStatus("/customEvents") end)
  probe("api.get /debugMessages", function() return getStatus("/debugMessages") end)
  probe("api.get self device", function() return getStatus("/devices/" .. self.id) end)
  probe("api.get self plugin", function() return getStatus("/plugins/" .. self.id) end)
  probe("api.get absent route", function() return getStatus("/no/such/route") end)

  -- updateProperty round trip with a string value (the HC3's string-value
  -- quirk family) and a number — read back via self.properties, the HC3's
  -- way (it has no getProperty)
  probe("updateProperty/getProperty", function()
    self:updateProperty("fluaParityProp", "hello")
    return self.properties.fluaParityProp
  end)
  probe("updateProperty number", function()
    self:updateProperty("fluaParityNum", 42)
    return self.properties.fluaParityNum
  end)

  -- updateView exists on both sides; the HC3 has no getView, so only the
  -- write itself is probed
  probe("updateView", function()
    self:updateView("fluaParityLabel", "text", "hello")
    return "ok"
  end)

  -- an absent global variable is nil on both sides
  probe("fibaro.getGlobalVariable absent", function()
    local gv = fibaro.getGlobalVariable("fluaParityProbe")
    return gv == nil and "nil" or "value"
  end)

  -- an unknown fibaro function errors on both sides
  probe("fibaro.nope", function()
    local okNope = pcall(function() return fibaro.nope() end)
    return okNope and "callable" or "error"
  end)

  self:debug("PROBE_DONE")
  setTimeout(function() self:debug("PROBE timer fired") end, 100)
end
