--%%name:api-demo

function QuickApp:onInit()
  print("QuickApp API demo initialized")
  print("Value:",fibaro.getValue(self.id, "value"))

  local a = fibaro.getGlobalVariable("A")
  print(a)

  print(api.post("/globalVariables",{name='FLUA', value='1'}))
  print(fibaro.getGlobalVariable("FLUA"))
  local b = fibaro.setGlobalVariable("FLUA","2")
  print(fibaro.getGlobalVariable("FLUA"))
end