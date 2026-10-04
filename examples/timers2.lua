--%%name:timer2-demo

function QuickApp:onInit()
  setInterval(function() print("interval: 1s") end, 1000)
  setTimeout(function() print("timeout: 4s") exit() end, 4000)
end
