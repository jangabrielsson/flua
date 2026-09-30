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

  print("<font color='red'>HELLO</font>")
  print("<font color='green'><i>HELLO</i></font>")
  print("<table><tr><td>HELLO</td><td></td><td>A</td></tr><tr><td>WORLD</td></tr></table>")
end
