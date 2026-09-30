--%%name: sleep
--%%type:com.fibaro.binarySwitch

-- Sleep preventing other messages from being processed immediately, including timers

local function test1()
  print("Test 1 executed, 2s later") -- actually executess 3 seconds later, waiting for the sleep in onInit
end

function QuickApp:onInit()
  self:debug("QuickApp initialized")
  setTimeout(function()
    setTimeout(test1, 2000)
    fibaro.sleep(3000)
    print("Slept for 3 seconds in onInit")
  end,0)
end
