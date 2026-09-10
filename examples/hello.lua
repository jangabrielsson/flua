--%%name:hello
-- hello.lua — minimal flua QuickApp
print("Hello from", _FLUA.config.name, _FLUA.version)

local n = 0
local iv
iv = setInterval(function()
  n = n + 1
  print("tick", n)
  if n >= 3 then
    clearInterval(iv)
    print("done")
    exit(0)
  end
end, 400)
