-- @module fibaro.quickapp
---@description QuickApp core functionality for flua
---@author Jan Gabrielsson
---@license MIT
---
---This module provides the QuickApp base class and related utilities:
---- QuickApp lifecycle management
---- Device and UI interaction
---- Logging and event handling
_FLUA = _FLUA or {}

local fmt = string.format
local printErr = function(e) print("Error: " .. tostring(e)) end

function class(name)
  local cls = setmetatable({__USERDATA=true}, {
    __call = function(t,...)
      assert(rawget(t,'__init'),"No constructor")
      local obj = {__USERDATA=true}
      setmetatable(obj,{__index=t, __tostring = t.__tostring or function() return "object "..name end})
      obj:__init(...)
      return obj
    end,
    __tostring = function() return "class "..name end,
  })
  cls.__org = cls
  _ENV[name] = cls
  return function(p) getmetatable(cls).__index = p end
end

plugin = plugin or { mainDeviceId = _FLUA.qaId }

-- Retrieves a device by its ID
-- @param deviceId - The ID of the device to retrieve
-- @return Device object from the HC3 API
function plugin.getDevice(deviceId) return api.get("/devices/"..deviceId) end

-- Deletes a device by its ID
-- @param deviceId - The ID of the device to delete
-- @return Result of the delete operation
function plugin.deleteDevice(deviceId) return api.delete("/devices/"..deviceId) end

-- Gets a specific property of a device
-- @param deviceId - The ID of the device
-- @param propertyName - The name of the property to retrieve
-- @return The property value
function plugin.getProperty(deviceId, propertyName) return api.get("/devices/"..deviceId).properties[propertyName] end

-- Gets all child devices of a parent device
-- @param deviceId - The ID of the parent device
-- @return Array of child device objects
function plugin.getChildDevices(deviceId) return api.get("/devices?parentId="..deviceId) end

-- Creates a new child device
-- @param opts - Options for creating the child device
-- @return The created child device object
function plugin.createChildDevice(opts) return api.post("/plugins/createChildDevice", opts) end

-- Restarts a QuickApp plugin
-- @param id - The device ID to restart (optional, defaults to mainDeviceId)
-- @return Result of the restart operation
function plugin.restart(id)
  local result = api.post("/plugins/restart",{deviceId=id or plugin.mainDeviceId})
  -- like the HC3: the process dies at the call, so code after it must not
  -- run — abort the current turn silently (the restart is already posted)
  if _FLUA and _FLUA.restartAbort then error(_FLUA.restartAbort) end
  return result
end

NONE = 0;
ERROR = 1;
WARNING = 2;
DEBUG = 3;
TRACE = 4;

-- default: everything logs (the HC3 behavior) — a QA may lower this to
-- silence self:debug/trace/warning/error below a level
LOG_LEVEL = TRACE+1;

class 'QuickAppBase'
-- Constructor for QuickAppBase class
-- @param dev - Device object containing device properties and metadata
function QuickAppBase:__init(dev)
  self.id = dev.id
  self.type = dev.type
  self.name = dev.name
  self.enabled = dev.enabled
  self.parentId = dev.parentId
  self.roomID = dev.roomID
  self.properties = dev.properties
  self.interfaces = dev.interfaces
  self.uiCallbacks = {}
  -- (the engine's bootstrap registers the instance; see _FLUA.qa)
end

-- Logs a debug message with the device tag
-- @param ... - Arguments to be logged
function QuickAppBase:debug(...) 
  if LOG_LEVEL < DEBUG then return end
  fibaro.debug(__TAG,...)
end

-- Logs a trace message with the device tag
-- @param ... - Arguments to be logged
function QuickAppBase:trace(...) 
  if LOG_LEVEL < TRACE then return end
  fibaro.trace(__TAG,...)
end

-- Logs a warning message with the device tag
-- @param ... - Arguments to be logged
function QuickAppBase:warning(...) 
  if LOG_LEVEL < WARNING then return end
  fibaro.warning(__TAG,...)
end

-- Logs an error message with the device tag
-- @param ... - Arguments to be logged
function QuickAppBase:error(...) 
  if LOG_LEVEL < ERROR then return end
  fibaro.error(__TAG,...)
end

-- Registers a UI callback function for a specific element and event type
-- @param elm - The UI element name
-- @param typ - The event type (e.g., "onReleased", "onChanged")
-- @param fun - The callback function to register
function QuickAppBase:registerUICallback(elm, typ, fun)
  local uic = self.uiCallbacks
  uic[elm] = uic[elm] or {}
  uic[elm][typ] = fun
end

-- Sets up UI callbacks based on device properties
-- Reads uiCallbacks from device properties and registers them
function QuickAppBase:setupUICallbacks()
  local callbacks = (self.properties or {}).uiCallbacks or {}
  for _, elm in pairs(callbacks) do
    self:registerUICallback(elm.name, elm.eventType, elm.callback)
  end
end

QuickAppBase.registerUICallbacks = QuickAppBase.setupUICallbacks

-- Calls an action method on the QuickApp if it exists
-- @param name - The name of the action/method to call
-- @param ... - Arguments to pass to the action method
-- @return Result of the action method or nil if method doesn't exist
function QuickAppBase:callAction(name, ...)
  --if name == "" then return end
  local args = {...}
  local stat,res = xpcall(function()
    if (type(self[name]) == 'function') then return self[name](self, table.unpack(args))
    else print(fmt("[WARNING] Class does not have '%s' function defined - action ignored",tostring(name))) end
  end,function(e) printErr(e) return e end)  -- print AND return: the strict-failure record needs the original error
  if not stat then
    self:error(fmt("Error calling action %s: %s",name,res))
    -- --strict-tests: the framework catches action errors HERE (the outer
    -- coroutine dispatch never sees them — the mapped-callback path
    -- onUIEvent -> timer -> callAction swallows the error in this xpcall).
    -- Record it so a mapped UI/action callback error stays sticky, like
    -- timer/net errors. Application-owned pcall never reaches this branch.
    _PY.record_callback_failure(_FLUA.qaId, "ui", tostring(res))
  end
end

-- Updates a device property and sends the update to the HC3 system
-- @param name - The name of the property to update
-- @param value - The new value for the property
function QuickAppBase:updateProperty(name,value)
  self.properties[name] = value
  api.post("/plugins/updateProperty",{
    deviceId=self.id,
    propertyName=name,
    value=value
  })
end

-- Updates a UI view element property
-- @param elm - The UI element name
-- @param prop - The property name to update
-- @param value - The new value for the property
function QuickAppBase:updateView(elm,prop,value)
  api.post("/plugins/updateView", {
    deviceId = self.id,
    componentName = elm,
    propertyName = prop,
    newValue = value
  })
end

-- Returns the QA's current rendered view (the $jason viewLayout, including
-- updateView changes). Same API as the HC3; handy for asserting UI state
-- from inside a verify QA.
function QuickAppBase:getView()
  local data, status = api.get("/plugins/getView?id=" .. self.id)
  if status == 200 then
    return data
  end
end

-- Checks if the device has a specific interface
-- @param name - The interface name to check for
-- @return True if the device has the interface, false otherwise
---@diagnostic disable-next-line: undefined-field
function QuickAppBase:hasInterface(name) return table.member(name, self.interfaces) end

-- Adds new interfaces to the device
-- @param values - Table of interface names to add
function QuickAppBase:addInterfaces(values)
  assert(type(values) == "table")
  self:updateInterfaces("add",values)
  for _, v in pairs(values) do
    table.insert(self.interfaces, v)
  end
end

-- Removes interfaces from the device
-- @param values - Table of interface names to remove
function QuickAppBase:deleteInterfaces(values)
  assert(type(values) == "table")
  self:updateInterfaces("delete", values)
  for _, value in pairs(values) do
    for key, interface in pairs(self.interfaces) do
      if interface == value then
        table.remove(self.interfaces, key)
        break
      end
    end
  end
end

-- Updates device interfaces via API call
-- @param action - The action to perform ("add" or "delete")
-- @param interfaces - Table of interfaces to add or remove
function QuickAppBase:updateInterfaces(action, interfaces)
  api.post("/plugins/interfaces", {action = action, deviceId = self.id, interfaces = interfaces})
end

-- Sets the device name
-- @param name - The new name for the device
function QuickAppBase:setName(name) api.put("/devices/"..self.id,{name=name}) end

-- Sets the device enabled state
-- @param enabled - Boolean indicating if device should be enabled
function QuickAppBase:setEnabled(enabled) api.put("/devices/"..self.id,{enabled=enabled}) end

-- Sets the device visibility
-- @param visible - Boolean indicating if device should be visible
function QuickAppBase:setVisible(visible) api.put("/devices/"..self.id,{visible=visible}) end

-- Sets a QuickApp variable value
-- @param name - The variable name
-- @param value - The variable value
function QuickAppBase:setVariable(name, value)
  local qvars,found = self.properties.quickAppVariables,false
  for _,v in ipairs(qvars) do
    if v.name == name then
      v.value = value
      found = true
      break
    end
  end
  if not found then
    table.insert(qvars, {name=name, value=value})
  end
  self:updateProperty("quickAppVariables", qvars)
end

-- Gets a QuickApp variable value
-- @param name - The variable name
-- @return The variable value or empty string if not found
function QuickAppBase:getVariable(name)
  local qvars = self.properties.quickAppVariables
  for _,v in ipairs(qvars) do
    if v.name == name then
      return v.value
    end
  end
  return ""
end

-- Sets a value in internal storage
-- @param key - The storage key
-- @param val - The value to store
-- @param hidden - Boolean indicating if the variable should be hidden
-- @return HTTP status code
function QuickAppBase:internalStorageSet(key, val, hidden)
  __assert_type(key, 'string')
  local data = { name = key, value = val, isHidden = hidden }
  local _, stat = api.put("/plugins/" .. self.id .. "/variables/" .. key, data)
  --print(key,stat)
  if stat > 206 then
    local _, stat = api.post("/plugins/" .. self.id .. "/variables", data)
    --print(key,stat)
    return stat
  end
end

-- Gets a value from internal storage
-- @param key - The storage key (optional, if nil returns all variables)
-- @return The stored value or nil if not found
function QuickAppBase:internalStorageGet(key)
  --__assert_type(key, 'string')
  if key then
    local res, stat = api.get("/plugins/" .. self.id .. "/variables/" .. key)
    if stat ~= 200 then return nil end
    return res.value
  else
    local res, stat = api.get("/plugins/" .. self.id .. "/variables")
    if stat ~= 200 then return nil end
    local values = {}
    for _, v in pairs(res) do values[v.name] = v.value end
    return values
  end
end

-- Removes a variable from internal storage
-- @param key - The storage key to remove
-- @return Result of the delete operation
function QuickAppBase:internalStorageRemove(key) return api.delete("/plugins/" .. self.id .. "/variables/" .. key) end

-- Clears all variables from internal storage
-- @return Result of the delete operation
function QuickAppBase:internalStorageClear() return api.delete("/plugins/" .. self.id .. "/variables") end

class 'QuickApp'(QuickAppBase)
-- Constructor for QuickApp class (main QuickApp instance)
-- @param dev - Device object containing device properties and metadata
function QuickApp:__init(dev)
  __TAG = dev.name..dev.id
  plugin.mainQA = self
  QuickAppBase.__init(self, dev)
  self.childDevices = {}
  self.childsInitialized = false
  self:setupUICallbacks()
  if self.onInit then self:onInit() end
  quickApp = self
  if not self.childsInitialized then self:initChildDevices() end
end

-- Initializes child devices for this QuickApp
-- @param map - Optional mapping table of device types to constructor functions
---@diagnostic disable-next-line: duplicate-set-field
function QuickApp:initChildDevices(map)
  map = map or {}
  local children = api.get("/devices?parentId="..self.id)
  local childDevices = self.childDevices
  for _, c in pairs(children) do
    if childDevices[c.id] == nil and map[c.type] then
      childDevices[c.id] = map[c.type](c)
    elseif childDevices[c.id] == nil then
      self:error(fmt("Class for the child device: %s, with type: %s not found. Using base class: QuickAppChild", c.id, c.type))
      childDevices[c.id] = QuickAppChild(c)
    end
    ---@diagnostic disable-next-line: inject-field
    childDevices[c.id].parent = self
  end
  self.childsInitialized = true
end

-- Creates a new child device for this QuickApp
-- @param options - Options table containing device configuration
-- @param classRepresentation - Optional class constructor for the child device
-- @return The created child device instance
function QuickApp:createChildDevice(options, classRepresentation)
  __assert_type(options, "table")
  __assert_type(options.name, "string")
  __assert_type(options.type, "string")
  options.parentId = self.id
  if options.initialInterfaces then
    __assert_type(options.initialInterfaces, "table")
    table.insert(options.initialInterfaces, "quickAppChild")
  else
    options.initialInterfaces = {"quickAppChild"}
  end
  if options.initialProperties then
    __assert_type(options.initialProperties, "table")
  end
  local child = api.post("/plugins/createChildDevice", options)
  if classRepresentation == nil then
    classRepresentation = QuickAppChild
  end
  self.childDevices[child.id] = classRepresentation(child)
  ---@diagnostic disable-next-line: inject-field
  self.childDevices[child.id].parent = self
  
  return self.childDevices[child.id]
end

-- Removes a child device of this QuickApp
-- @param id - The device id of the child to remove
-- @return The api.delete result (data, status)
function QuickApp:removeChildDevice(id)
  if self.childDevices[id] then
    local res,code = api.delete("/plugins/removeChildDevice/" .. id)
    self.childDevices[id] = nil
    return res,code
  end
end

class 'QuickAppChild'(QuickAppBase)
-- Constructor for QuickAppChild class (child device of a QuickApp)
-- @param dev - Device object containing device properties and metadata
function QuickAppChild:__init(dev)
  QuickAppBase.__init(self, dev)
  self.parentId = dev.parentId
  if self.onInit then self:onInit() end
end

-- Global handler for device actions
-- Routes actions to the appropriate QuickApp or child device
-- @param id - Device ID where the action was called
-- @param event - Event object containing action details
function onAction(id,event) -- { deviceID = 1234, actionName = "test", args = {1,2,3} }
  --if Emu:DBGFLAG('onAction') then print("onAction: ", json.encode(event)) end
  -- if quickApp then quickApp:trace("onAction: ", json.encode(event)) end
  setTimeout(function()
  local self = plugin.mainQA
  ---@diagnostic disable-next-line: undefined-field
  if self.actionHandler then return self:actionHandler(event) end
  if event.deviceId == self.id then
    return self:callAction(event.actionName, table.unpack(event.args or {}))
  elseif self.childDevices[event.deviceId] then
    return self.childDevices[event.deviceId]:callAction(event.actionName, table.unpack(event.args or {}))
  end
  self:error(fmt("Child with id:%s not found",id))
end,0)
end

-- Global handler for UI events
-- Routes UI events to the appropriate QuickApp callbacks
-- @param id - Device ID where the UI event occurred
-- @param event - Event object containing UI event details
function onUIEvent(id, event)
  local quickApp = plugin.mainQA
  --print("onUIEvent",json.encode(event))
  --if Emu:DBGFLAG('onUIEvent') then print("UIEvent: ", json.encode(event)) end
  ---@diagnostic disable-next-line: undefined-field
  if quickApp.UIHandler then quickApp:UIHandler(event) return end
  if quickApp.uiCallbacks[event.elementName] and quickApp.uiCallbacks[event.elementName][event.eventType] then
    local action = quickApp.uiCallbacks[event.elementName][event.eventType]
    if action == "" then
      fibaro.warning(__TAG,fmt("UI callback for %s %s not found.", event.elementName, event.eventType))
      return
    end
    setTimeout(function() quickApp:callAction(action, event) end,0)
  else
    fibaro.warning(__TAG,fmt("UI callback for element %s not found.", event.elementName))
  end
end

-- Programmatically triggers a UI action for testing purposes
-- @param eventType - The type of UI event to trigger
-- @param elementName - The name of the UI element
-- @param arg - Optional argument value for the event; like the HC3, the
--   argument is wrapped once: event.values[1] is the scalar for sliders
--   and single selects, and the whole selected-values list for multi
--   selects
function QuickAppBase:UIAction(eventType, elementName, arg)
  local event = {
    deviceId = self.id,
    eventType = eventType,
    elementName = elementName
  }
  event.values = arg ~= nil and { arg } or json.util.InitArray({})
  onUIEvent(self.id, event)
end

---@class RefreshStateSubscriber
---@field time number - Time to skip events before this timestamp
---@field subscribers table - Table of subscribers with their filters and handlers
---@field last number - Last processed event timestamp
---@field subject table - Subject for handling refresh state events
RefreshStateSubscriber = {}
class 'RefreshStateSubscriber'

-- Constructor for RefreshStateSubscriber class
-- Initializes the subscriber for refresh state events
function RefreshStateSubscriber:__init()
  self.time = os.time() -- Skip events before this time
  self.subscribers = {}
  self.last = 0
  function self.handle(event)
    event.created = event.created or os.time()
    if self.time > event.created+2 then return end -- Allow for 2 seconds mismatch between emulator and HC3
    for sub,_ in pairs(self.subscribers) do
      if sub.filter(event) then pcall(sub.handler,event) end
    end
  end
end

-- Subscribes to refresh state events with a filter and handler
-- @param filter - Function to filter events (return true to handle)
-- @param handler - Function to handle matching events
-- @return Subscription object
function RefreshStateSubscriber:subscribe(filter, handler)
  return self.subject:filter(function(event) return filter(event) end):subscribe(function(event) handler(event) end)
end

local MTsub = { __tostring = function(self) return "Subscription" end }

local SUBTYPE = '%SUBSCRIPTION%'
-- Subscribes to refresh state events with a filter and handler (alternative implementation)
-- @param filter - Function to filter events (return true to handle)
-- @param handler - Function to handle matching events
-- @return Subscription object
function RefreshStateSubscriber:subscribe(filter, handler)
  local sub = setmetatable({ type=SUBTYPE, filter = filter, handler = handler },MTsub)
  self.subscribers[sub]=true
  return sub
end

-- Unsubscribes from refresh state events
-- @param subscription - The subscription object to remove
function RefreshStateSubscriber:unsubscribe(subscription)
  if type(subscription)=='table' and subscription.type==SUBTYPE then
    self.subscribers[subscription]=nil
  end
end

local listeners = {}

-- Starts the refresh state subscriber
---@diagnostic disable-next-line: undefined-field
function RefreshStateSubscriber:run()
  -- flua: events arrive through the message pump (handlers.refreshStateEvent).
  -- The registry maps handle -> owning qaId so delivery can skip a sleeping QA.
  _FLUA.refreshStateListeners[self.handle] = _FLUA.qaId
end

-- Stops the refresh state subscriber
---@diagnostic disable-next-line: undefined-field
function RefreshStateSubscriber:stop() 
  _FLUA.refreshStateListeners[self.handle] = nil
end

-- icon providers and device icon type mapping
QuickAppBase.iconProviders = {
    single = {
        info = "One icon is required for this device type",
        fileNames = {"icon"}
    },
    binary = {
        info = "Two icons are required for this device type (state off, state on)",
        fileNames = {"icon0", "icon100"}
    },
    multilevel = {
        info = "11 icons are required for this device type (states: 0%, 10%, 20%, 30%, 40%, 50%, 60%, 70%, 80%, 90%, 100%)",
        fileNames = {"icon0", "icon10", "icon20", "icon30", "icon40", "icon50", "icon60", "icon70", "icon80", "icon90", "icon100"}
    },
    baseShutter = {
        info = "5 icons are required for this device type (states: Opening, Opened, Closing, Closed, Unknown)",
        fileNames = {"iconOpening", "iconOpened", "iconClosing", "iconClosed", "iconUnknown"}
    }
}

-- Mapping of device types to their corresponding icon providers
QuickAppBase.deviceIconTypeMapping = {
    ["com.fibaro.humiditySensor"] = QuickAppBase.iconProviders.single,
    ["com.fibaro.powerSensor"] = QuickAppBase.iconProviders.single,
    ["com.fibaro.energyMeter"] = QuickAppBase.iconProviders.single,
    ["com.fibaro.temperatureSensor"] = QuickAppBase.iconProviders.single,
    ["com.fibaro.windSensor"] = QuickAppBase.iconProviders.single,
    ["com.fibaro.multilevelSensor"] = QuickAppBase.iconProviders.single,
    ["com.fibaro.binarySwitch"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.doorLock"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.binarySensor"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.doorSensor"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.floodSensor"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.smokeSensor"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.windowSensor"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.motionSensor"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.rainDetector"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.heatDetector"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.gasDetector"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.coDetector"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.fireDetector"] = QuickAppBase.iconProviders.binary,
    ["com.fibaro.multilevelSwitch"] = QuickAppBase.iconProviders.multilevel,
    ["com.fibaro.rollerShutter"] = QuickAppBase.iconProviders.multilevel,
    ["com.fibaro.baseShutter"] = QuickAppBase.iconProviders.baseShutter,
    ["com.fibaro.deviceController"] = QuickAppBase.iconProviders.single,
    ["com.fibaro.genericDevice"] = QuickAppBase.iconProviders.single,
    ["com.fibaro.player"] = QuickAppBase.iconProviders.single,
}

-- Method that will upload provided icons for the given deviceType 
-- @providerContext - a table with the following structure
--    fileNames - an array of filenames that will be used for the upload. Its size must match the size of files array.
--    files - an array with icons content. Its size must match the size of fileNames array.   
--    deviceType - type of the device that will be used for the upload.
-- @options - a table with some additional options (can be extended in the future). For now, it isn't used in this method.
-- @successCallback (optional) - a function that will be called after a successful upload. iconId (int) will be passed as the first argument to this function.  
-- @errorCallback (optional) - a function that will be called on error during the upload process. requestError (string) will be passed as the first argument to this function.
function QuickAppBase:uploadIconFiles(providerContext, options, successCallback, errorCallback)
    local http = net.HTTPClient({timeout=3000}) 

    local rawIcons = providerContext.files
    local deviceType = providerContext.deviceType
    local fileNames = providerContext.fileNames

    local boundary = "------HCFormBoundary20838a8df7cc0babd745c7af4b7d94e2"
    local formBoundary = "--" .. boundary
    local CRLF = "\r\n";

    -- setup some base form data: icon type (type field) and device type (deviceTemplate field)
    local content = 
        formBoundary .. CRLF ..
        "Content-Disposition: form-data; name=\"type\"" .. CRLF ..
        CRLF ..
        "device" .. CRLF ..
        formBoundary .. CRLF ..
        "Content-Disposition: form-data; name=\"deviceTemplate\"" .. CRLF ..
        CRLF ..
        deviceType .. CRLF ..
        formBoundary .. CRLF 

    -- add icons data to the form
    for key,rawIcon in pairs(rawIcons) do
        local fileName = fileNames[key]
        local endOfBoundary = CRLF

        -- at the end of the form data (after the last element), we need to add an additional '--'
        if key == #rawIcons then 
            endOfBoundary = "--" .. endOfBoundary 
        end

        content = content .. "Content-Disposition: form-data; name=\"" .. fileName .. "\"; filename=\"" .. fileName .. "\"" .. CRLF ..
        "Content-Type: image/png" .. CRLF ..
        CRLF ..
        rawIcon .. CRLF ..
        formBoundary .. endOfBoundary
    end

    http:request("http://127.0.0.1:11111/api/icons", {
        options={
            headers = { 
                ["Content-Type"] = "multipart/form-data; boundary=" .. boundary,
                ["Accept"] = "application/json"
            },
            method = 'POST',
            data = content
        },
        success = function(response)
            if (response.status == 201) then
                if successCallback then
                    local responseJson = json.decode(response.data)
                    successCallback(responseJson.id)
                end
            else
                local errorMessage = "Error while uploading icon. Status: " .. tostring(response.status) .. ". Response: " .. response.data
                if errorCallback then
                    errorCallback(errorMessage)
                else
                    self:error(errorMessage)
                end
            end
        end,
        error = function(requestError)
            local errorMessage = "Error while uploading icon. " .. requestError
            if errorCallback then
                errorCallback(errorMessage)
            else
                self:error(errorMessage)
            end        
        end
    })  
end

-- Method for downloading external icons. It will run itself recursively until all files are downloaded. 
-- After downloading all files, QuickAppBase:uploadIconFiles method will be run. 
-- @providerContext - a table with the following structure
--    fileNames - an array of filenames that will be used for the upload. 
--    files - an array with icons content. One file is added in each iteration. Its size should match fileNames table after all files are downloaded. 
--    url -  an array of file urls to download. Its size should match fileNames table.
--    index - current iteration number and an index used to extract url of the file to download.
--    deviceType - type of the device that will be used for the upload.
-- @options - a table with some additional options (can be extended in the future)
--    checkCertificate (default true) - when set to false, it will ignore host validation during HTTPS connection. Has no effect on the HTTP connections.
-- @successCallback (optional) - a function that will be called after a successful upload. iconId (int) will be passed as the first argument to this function.  
-- @errorCallback (optional) - a function that will be called on error during the download or upload process. requestError (string) will be passed as the first argument to this function.
function QuickAppBase:externalIconsDownload(providerContext, options, successCallback, errorCallback)
    local http = net.HTTPClient({timeout=3000}) 
    local index = providerContext.index
    local url = providerContext.urls[index]
    local checkCertificate = true

    if options.checkCertificate ~= nil then
        checkCertificate = options.checkCertificate
    end

    http:request(url, {
        options={
            checkCertificate = checkCertificate,
            method = 'GET'
        },
        success = function(response)
            if response.status < 200 or response.status >= 300  then
                local errorMessage = "Error while downloading icon: " .. url .. ". Status: " .. tostring(response.status) .. ". Response: " .. response.data
                if errorCallback then
                    errorCallback(errorMessage)
                else
                    self:error(errorMessage)
                end
                return
            end

            providerContext.files[index] = response.data

            if index == #providerContext.urls then
                -- all ions files downloaded, going to upload
                self:uploadIconFiles(providerContext, options, successCallback, errorCallback)
            else
                -- download another file from the list 
                providerContext.index = index + 1
                self:externalIconsDownload(providerContext, options, successCallback, errorCallback)
            end
        end,
        error = function(requestError)
            local errorMessage = "Error while downloading icon: " .. url .. ". Error: " .. requestError
            if errorCallback then
                errorCallback(errorMessage)
            else
                self:error(errorMessage)
            end  
        end
    })
end

-- Method that will add a new icon set for the device type and set it for the current device. 
-- @urls - an array of file urls to download. Its size should match the files count required for the device type.
-- @options - a table with some additional options (can be extended in the future)
--    checkCertificate (default true) - when set to false, it will ignore host validation during HTTPS connection. Has no effect on the HTTP connections.
-- @successCallback (optional) - a function that will be called after a successful upload. iconId (int) will be passed as the first argument to this function.  
-- @errorCallback (optional) - a function that will be called on error during the download or upload process. requestError (string) will be passed as the first argument to this function.
function QuickAppBase:uploadExternalIconSet(urls, options, successCallback, errorCallback)
    if options == nil then
        options = {}
    end

    local deviceType = self.type
    local provider = QuickApp.deviceIconTypeMapping[deviceType]
    
    if provider == nil then
        error("Unsupported type " .. tostring(deviceType), 2)
    end

    -- provided urls count must match files count required by the device type 
    if #urls ~= #provider.fileNames then
        error(provider.info .. ", provided: " .. tostring(#urls), 2)
    end

    local providerContext = {
        fileNames = provider.fileNames,
        files = {},
        urls = urls,
        index = 1,
        deviceType = deviceType
    }

    self:externalIconsDownload(providerContext, options, 
        function(iconId)
            -- set uploaded icon set for current device 
            self:updateProperty("deviceIcon", iconId)
            if successCallback then
                successCallback(iconId)
            end
        end, 
        errorCallback)
end 
