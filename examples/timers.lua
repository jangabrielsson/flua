--%%name:timer-demo
-- timers.lua — setTimeout, clearTimeout, and chained timers
print("-- timer demo --")

setTimeout(function() print("one shot: 1s") end, 1000)

local late = setTimeout(function() print("should NOT print") end, 2000)
setTimeout(function()
  print("cancelling the late timer")
  clearTimeout(late)
end, 500)

setTimeout(function()
  print("chain: step 2")
  setTimeout(function()
    print("chain: step 3")
    exit(0)
  end, 300)
end, 1500)
