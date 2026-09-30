--%%name:restart test

-- A QA restart re-runs onInit with the device struct intact: the boot
-- counter is a quickAppVariable, so it survives plugin.restart. The sleep
-- inside onInit also works (flua defers onInit until the instance is
-- registered). The counter bounds the restarts so the example terminates.

function QuickApp:onInit()
  local n = tonumber(self:getVariable("boots")) or 0
  n = n + 1
  self:setVariable("boots", tostring(n))
  self:debug("Initializing QuickApp", n)
  fibaro.sleep(2000)
  if n < 3 then
    plugin.restart(self.id)
  end
end
