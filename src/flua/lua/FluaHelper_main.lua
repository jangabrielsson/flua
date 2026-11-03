--%%name:FluaHelper
--%%type:com.fibaro.binarySwitch
--%%property:useUiView=true
--%%property:typeTemplateInitialized=true
--%%property:userDescription=
--%%uid:flua-00-01
--%%model:1.1.0
-- --------------- EOH ---------------
-- Identity properties (quickAppUuid, model) are declared as --%%uid/
-- --%%model so they ride the .fqa as INITIAL properties: the HC3 ignores
-- runtime updateProperty writes to them (installHelper discovers the
-- helper by quickAppUuid and compares model versions).
-- Version policy: bump HELPER_VERSION when the wire protocol changes OR a
-- deployed helper must be replaced (bugfixes) — installHelper compares this
-- version against the deployed helper's to decide replace vs keep.
local HELPER_UUID = "flua-00-01"
local HELPER_VERSION = "1.3.0"

function QuickApp:onInit()
    self:debug(self.name,self.id)
    self:updateProperty('quickAppUuid',HELPER_UUID)
    self:updateProperty('model',HELPER_VERSION)
end

local connections = {}

local function newConnection(url)
    local ws = net.WebSocketClient()
    
    ws:addEventListener("connected", function()
      print("Connection from",url)
    end)
    
    ws:addEventListener("dataReceived", function(data)
      -- Only close after receiving echo message (not welcome message)
      print("Receieved from", url, #data)
      if data == "ping" then return ws:send("pong") end
      -- the whole handler is wrapped: any error becomes an RPC error reply
      -- instead of silently killing the connection
      local rid
      local okH, errH = pcall(function()
        local stat,req = pcall(json.decode,data)
        if not stat then error(req) end
        rid = req.id
        if req.kind == "fibaro" then
          -- fibaro.<name>(...): run a controller-side fibaro function
          -- (parity probes, real device actions). fibaro is a plain table
          -- of name->function. Runs in the HELPER QA's context;
          -- fibaro.sleep would block the helper (drop the connection):
          -- don't. values echoes every return value.
          local fn = fibaro[req.name]
          if type(fn) ~= "function" then
            ws:send(json.encode({
              id = req.id, ok = false,
              values = { "fibaro." .. tostring(req.name) .. " is not a function" },
            }))
          else
            local res = {pcall(fn, table.unpack(req.args or {}))}
            ws:send(json.encode({ id = req.id, ok = res[1], values = {select(2, table.unpack(res))} }))
          end
        else
          -- the HC3's api table has LOWERCASE method keys (api.get, api.post,
          -- ...) — indexing with the uppercase wire method is nil (the
          -- "attempt to call a nil value" bug)
          local call = {
            GET = api.get,
            POST = api.post,
            PUT = api.put,
            DELETE = api.delete,
          }
          local res = {pcall(call[req.method], req.path, req.data)}
          -- res = {ok, data, status} — echo the request id so the emulator
          -- can match the reply to its pending call
          ws:send(json.encode({ id = req.id, ok = res[1], data = res[2], status = res[3] }))
        end
      end)
      if not okH then
        local payload = { id = rid, ok = false, values = { "handler error: " .. tostring(errH) } }
        local okE, encE = pcall(json.encode, payload)
        if not okE then encE = json.encode({ id = rid, ok = false, values = { "handler error (unencodable): " .. tostring(errH) } }) end
        pcall(function() ws:send(encE) end)
      end
    end)
    
    ws:addEventListener("disconnected", function()
      print("Disconnected",url)
      connections[url] = nil
      -- no re-dial: the connection is dead until flua asks for it again
      -- (its connect action fires on demand when flua needs to send)
    end)
    
    ws:addEventListener("error", function(err)
      print("Error, disconnected", url, err)
      connections[url] = nil
    end)
    
    print(url,":",ws:connect(url))
    return true
end

function QuickApp:connect(url)
    if not connections[url] then
       setTimeout(function()
         connections[url] = newConnection(url)
         end,0)
    else
       -- same flua asking again: drop the stale socket first (a reconnect
       -- must not leak the old connection)
       local old = connections[url]
       old:close()
       connections[url] = nil
       setTimeout(function()
         connections[url] = newConnection(url)
         end,0)
    end
end
