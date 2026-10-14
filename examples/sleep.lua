--%%name: sleep
--%%type:com.fibaro.binarySwitch

-- Sleep preventing other messages from being processed immediately, including timers

local function test1()
  print("Test 1 executed, 400ms later") -- actually executes 600ms later, waiting for the sleep in onInit
end

function QuickApp:onInit()
  self:debug("QuickApp initialized")
  setTimeout(function()
    setTimeout(test1, 400)
    fibaro.sleep(600)
    print("Slept for 600ms in onInit")
  end,0)
end
