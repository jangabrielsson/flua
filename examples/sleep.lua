--%%name: sleep
--%%type:com.fibaro.binarySwitch

local function test1()
  print("Test 1 executed, 2s later")
end

function QuickApp:onInit()
  self:debug("QuickApp initialized")
  setTimeout(function()
    setTimeout(test1, 2000)
    fibaro.sleep(3000)
    print("Slept for 3 seconds in onInit")
  end,0)
end
