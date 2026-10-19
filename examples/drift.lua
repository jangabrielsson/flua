last = os.time()
local function work()
  local a,t = 0,os.time()
  local t0 = os.clock()
  for i=1,10000*100*10*2 do a=a+1 end
  print(os.clock()-t0)
  print("work",t-last,os.date("%X"))
  last = t
end

local function loop(fun,sec)
    local t,ref = os.time()+sec,nil
    local function looper()
        fun()
        t=t+sec
        ref = setTimeout(looper,(t-os.time())*1000)
    end
    setTimeout(looper,(t-os.time())*1000)
end


function QuickApp:onInit()
    self:debug("onInit")
    setInterval(work,2000) -- This will drift
    --loop(work,2) -- this not...
end