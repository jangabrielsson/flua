--%%name:api-demo

function QuickApp:onInit()
  print("QuickApp API demo initialized")
  print("Value:",fibaro.getValue(self.id, "value"))
end