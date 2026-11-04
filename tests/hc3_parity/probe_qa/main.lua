--%%name:flua-p-probe
--%%type:com.fibaro.binarySwitch
-- --------------- EOH ---------------
-- Tier-3 parity probe QA. The SAME self-test runs on the HC3 (capture) and
-- in the sim (replay): every PROBE line is deterministic — status codes,
-- types and self-set values only, never names/ids of house objects — so
-- the two /debugMessages transcripts are directly comparable.
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

  local function getStatus(path)
    local _, status = api.get(path)
    return status
  end

  -- the read surface, status-only (house-independent)
  report("api.get /devices", getStatus("/devices"))
  report("api.get /plugins", getStatus("/plugins"))
  report("api.get /globalVariables", getStatus("/globalVariables"))
  report("api.get /settings/info", getStatus("/settings/info"))
  report("api.get /refreshStates", getStatus("/refreshStates"))
  report("api.get /rooms", getStatus("/rooms"))
  report("api.get /scenes", getStatus("/scenes"))
  report("api.get /customEvents", getStatus("/customEvents"))
  report("api.get /debugMessages", getStatus("/debugMessages"))
  report("api.get self device", getStatus("/devices/" .. self.id))
  report("api.get self plugin", getStatus("/plugins/" .. self.id))
  report("api.get absent route", getStatus("/no/such/route"))

  -- updateProperty round trip with a string value (the HC3's string-value
  -- quirk family) and a number
  self:updateProperty("fluaParityProp", "hello")
  report("updateProperty/getProperty", self:getProperty("fluaParityProp"))
  self:updateProperty("fluaParityNum", 42)
  report("updateProperty number", self:getProperty("fluaParityNum"))

  -- updateView round trip: the view table reflects the label
  self:updateView("fluaParityLabel", "text", "hello")
  local view = self:getView()
  local label = type(view) == "table" and view.fluaParityLabel
  report("updateView/getView", type(view) .. ":" .. (label or "absent"))

  -- an absent global variable is nil on both sides
  local gv = fibaro.getGlobalVariable("fluaParityProbe")
  report("fibaro.getGlobalVariable absent", gv == nil and "nil" or "value")

  -- an unknown fibaro function errors on both sides
  local okNope = pcall(function() return fibaro.nope() end)
  report("fibaro.nope", okNope and "callable" or "error")

  self:debug("PROBE_DONE")
  setTimeout(function() self:debug("PROBE timer fired") end, 100)
end
