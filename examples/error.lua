--%%name:ErrorTest
--%%type:com.fibaro.multilevelSwitch

local function foo()
  print("This is a test error function")
  error("This is a test error")
end
function QuickApp:onInit()
  print("Error test initialized")
  setTimeout(foo,1000)
end
