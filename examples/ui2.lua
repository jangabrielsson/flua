--%%name:UI test 2
--%%type:com.fibaro.binarySwitch

--%%u:{label="l1",text="<font color='red'>Label text</font>"}

function QuickApp:onInit()
  print("UI test 2 initialized")
  local n = 0 
  setInterval(function()
    n = n + 1
    self:updateView('l1','text',string.format("<font color='red'>%s</font>", n))
    print("Interval triggered")
  end, 1000)
end