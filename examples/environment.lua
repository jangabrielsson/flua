--%name:Environment
-- %mode:offline

for k,v in pairs(_FLUA) do
  print(k,v)
  if type(v) == 'table' then
    for kk,vv in pairs(v) do
      print('  ',kk,vv)
    end
  end
end
print("--------------------")
for k,v in pairs(_G) do
  print(k,v)
  if type(v) == 'table' then
    for kk,vv in pairs(v) do
      print('  ',kk,vv)
    end
  end
end