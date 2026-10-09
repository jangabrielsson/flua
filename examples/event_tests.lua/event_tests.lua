--%%name:EventTest
--%%type:com.fibaro.multilevelSwitch
--%%mode:online
--%%file:event_mgr.lua,event

local EM = fibaro.EventMgr()
EM.log = true

EM:addHandler({type='device', property='value'},function(event)
  print(json.encode(event))
end)

EM:addHandler({type='alarm'},function(event)
  print(json.encode(event))
end)

function QuickApp:onInit()
  setTimeout(function() self:updateProperty('value',55) end, 1000)
end
