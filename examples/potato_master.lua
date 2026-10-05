--%%name:PotatoMaster
--%%type:com.fibaro.multilevelSwitch
--%%offline:true
-- %%debug:true

local potato = "Potato"
function QuickApp:onInit()
  self:debug("onInit",self.name,self.id)
  local id = self.id
  setTimeout(function()
    print("passing",potato,"to",id+1)
    fibaro.call(id+1,"pass",potato)
  end,0)
  local n = 100
  for i=1,n do
    local friend = i == n and id or id+i+1
---@diagnostic disable-next-line: redundant-parameter
    _FLUA.loadQAfromFile("examples/potato_client.lua",{"var:friend="..friend})
  end
end

function QuickApp:pass(str)
  print("Got my",str,"back!")
end