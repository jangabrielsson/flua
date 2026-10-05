--%%name:UI test2 
--%%type:com.fibaro.binarySwitch

--%%u:{label="l1",text="<font color='red'>Label text</font>"}
--%%u:{label="l2",text=""}

--%%proxy:true

local table = [[
<table>
  <tr>
    <td>Row 1, Cell 1</td>
    <td>Row 1, Cell 2</td>
  </tr>
  <tr>
    <td>Row 2, Cell 1</td>
    <td>Row 2, Cell 2</td>
  </tr>
</table>
]]
function QuickApp:onInit()
  print("UI test 2 initialized")
  self:updateView('l2','text',table)
  local n = 0 
  setInterval(function()
    n = n + 1
    self:updateView('l1','text',string.format("<font color='red'>%s</font>", n))
    print("Interval triggered")
  end, 1000)
end