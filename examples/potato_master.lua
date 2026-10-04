--%%name:PotatoMaster
--%%type:com.fibaro.multilevelSwitch
--%%offline:true
-- %%debug:true

local potato = "Potato"
function QuickApp:onInit()
  self:debug("onInit",self.name,self.id)
  setTimeout(function()
    print("passing",potato,"to",5001)
    fibaro.call(5001,"pass",potato)
  end,0)
  local n = 100
  for i=1,n do
    local friend = i == n and 5000 or 5000+i+1
    _FLUA.loadQAfromFile("examples/potato_client.lua",{"var:friend="..friend})
  end
end

function QuickApp:pass(str)
  print("Got my",str,"back!")
end