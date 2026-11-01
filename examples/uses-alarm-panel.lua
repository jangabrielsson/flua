--%%name:uses-alarm-panel
-- A consumer QA: does NOT require the module — the AlarmPanel QA owns the
-- endpoints (cross-QA routing). Waits for the panel's liveness marker,
-- arms partition 1, and verifies arming -> armed with the events.
function QuickApp:onInit()
  local seenArming, seenArmed = false, false
  local sub = RefreshStateSubscriber()
  sub:subscribe(
    function(e) return e.data and e.data.id == 1 and e.data.property == "armed" end,
    function(e)
      print("EVENT", tostring(e.data.newValue))
      if e.data.newValue == false then seenArming = true end
      if e.data.newValue == true then seenArmed = true end
    end
  )
  sub:run()

  local tries = 0
  local function waitReady()
    tries = tries + 1
    local r, s = api.get("/vendor/alarm-panel/ready")
    if s == 200 then
      local _, armStatus = api.post("/alarms/v1/partitions/1/actions/arm")
      print("ARM", armStatus)
      if armStatus ~= 202 then exit(1) end
      poll()
    elseif tries >= 100 then
      print("VERDICT: panel never ready")
      exit(1)
    else
      setTimeout(waitReady, 10)
    end
  end

  local polls = 0
  function poll()
    polls = polls + 1
    if seenArmed or polls >= 100 then
      print("PHASE", seenArming, seenArmed)
      print(seenArming and seenArmed and "VERDICT: all passed" or "VERDICT: failed")
      exit(seenArming and seenArmed and 0 or 1)
    else
      setTimeout(poll, 10)
    end
  end

  setTimeout(waitReady, 10)
end
