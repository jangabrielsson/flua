--%%name:warn
--%%type:com.fibaro.binarySwitch
--%%warn:true

-- Test the warn directive

function QuickApp:onInit()

  local d = api.get("/devices/7777") -- try to get undefined device

  fibaro.setGlobalVariable("Nonexist", "test") -- set a non-existent global variable
end
