local ostime = os.time
-- local function ostime()
--     -- return math.floor(_FLUA.millitime() / 1000.0 + 0.5)
--     return _FLUA.millitime() // 1000
-- end

last = ostime()
local function work()
  local a,t = 0,ostime()
  local t0 = os.clock()
  for i=1,10000*100*10*20 do a=a+1 end
  print(os.clock()-t0)
  print("work",t-last,ostime())
  last = t
end

local function loop(fun,sec)
    local t,ref = os.time()+sec,nil
    local function looper()
        fun()
        local ot = ostime()
        print("ostime",ot,"current t",t,"next t",t+sec,"wait",t+sec-ot)
        t=t+sec
        ref = setTimeout(looper,(t-ot)*1000)
    end
    setTimeout(looper,(t-ostime())*1000)
end


function QuickApp:onInit()
    self:debug("onInit")
    --setInterval(work,2000) -- This will drift
    loop(work,2) -- this not...
end