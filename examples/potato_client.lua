--%%name:Potato
--%%type:com.fibaro.multilevelSwitch

function QuickApp:onInit()
  self:debug("onInit",self.name,self.id)
end

function QuickApp:pass(str)
  local friend = self:getVariable("friend")
  print(self.id,"pass",str,friend)
  fibaro.call(friend,"pass",str)
  gotPotato = true
  api.delete("/devices/"..self.id)
end
