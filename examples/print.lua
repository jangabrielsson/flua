print("Hello")
local a = {a =9}
print("a=",a)
setmetatable(a,{__tostring = function(self) return tostring(self.a) end})
print("a=",a) -- print respect __tostring

function QuickApp:onInit()
  self:debug("DEBUG")
  self:trace("TRACE")
  self:warning("WARN")
  self:error("ERROR")
end
