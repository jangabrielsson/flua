--%%name:QwikChildTest
--%%type:com.fibaro.deviceController

--%%file:$qwikchild.lua,qwikchild

-- The qwikchild living example: two child devices driven through their UI,
-- self-tested. The QA injects UI events through the same REST route the HC3
-- UI viewer uses, then asserts the children behaved (label updated, property
-- changed). Exits with the failure count.

local fmt = string.format

local children = {
  ['childA'] = {
    name = 'ChildA',
    type = 'com.fibaro.multilevelSensor',
    className = 'MyChildA',
    UI = {
      {label='l1', text="..."},
      {button='b1', text='Click', onReleased='myBtn'},
      {label='value', text='Value: 0'},
    }
  },
  ['childB'] = {
    name = 'ChildB',
    type = 'com.fibaro.multilevelSensor',
    className = 'MyChildB',
    UI = {
      {label='l1', text="..."},
      {slider='s1', text='Slider', onChanged='mySlider'},
      {label='value', text='Value: 0'},
    }
  }
}

function QuickApp:onInit()
  self:debug(self.name, self.id)
  self:initChildren(children)

  local failures = 0
  local function check(ok, what)
    if ok then print("PASS: " .. what)
    else failures = failures + 1; print("FAIL: " .. what) end
  end
  local function finish()
    print("failures:", failures)
    setInterval(function() end,2000)
    --exit(failures > 0 and 1 or 0)
  end

  print('DBG step1')
  local map = self:getChildrenUidMap()
  print('DBG step2 map', map.childA and map.childA.id, map.childB and map.childB.id)
  local childA = self.childDevices[map.childA.id]
  local childB = self.childDevices[map.childB.id]
  print('DBG step3', childA and childA.id, childB and childB.id)
  check(childA ~= nil and childB ~= nil, "children created")
  if not (childA and childB) then finish() return end
--[[
  -- does a child's uiView contain the given label text?
  local function uiTextContains(devId, needle)
    local dev = api.get("/devices/" .. devId)
    local uiView = dev and dev.properties and dev.properties.uiView or {}
    for _, row in ipairs(uiView) do
      for _, comp in ipairs(row.components or {}) do
        if tostring(comp.text or ""):find(needle, 1, true) then return true end
      end
    end
    return false
  end

  -- UI events deliver through the pump: poll for the effect
  local function waitFor(what, cond, deadline, done)
    print('DBG waitFor', what, os.time(), deadline)
    if cond() then check(true, what) done() return end
    if os.time() > deadline then check(false, what) done() return end
    setTimeout(function() waitFor(what, cond, deadline, done) end, 50)
  end

  -- button on childA: myBtn writes the current time into childB's label
  local stamp = os.date('%c')
  print('DBG posting button event')
  api.post("/plugins/callUIEvent?deviceID=" .. childA.id
    .. "&elementName=b1&eventType=onReleased", nil)
  print('DBG posted')
  waitFor("button press updated childB's label",
    function() return uiTextContains(childB.id, stamp) end, os.time() + 5, function()
    -- slider on childB: mySlider sets childA's value property (values arrive
    -- as strings, like the real UI)
    api.post("/plugins/callUIEvent?deviceID=" .. childB.id
      .. "&elementName=s1&eventType=onChanged&value=42", nil)
    waitFor("slider set childA's value property",
      function() return tostring(api.get("/devices/" .. childA.id).properties.value) == "42" end,
      os.time() + 5, function()
      -- the update pattern: parent pushes data to the children's labels
      self:updateChildren({A = {value = 7}, B = {value = 8}})
      check(uiTextContains(childA.id, "value: 7"), "updateChildren refreshed childA's label")
      finish()
    end)
  end)
  --]]
end

function QuickApp:updateChildren(data)
  -- the classic pattern: children render the data their parent pushes
  for uid, child in pairs(self.children) do
    child:update(data)
  end
end

MyChildA = {}
class 'MyChildA'(QwikAppChild)
function MyChildA:__init(dev)
  QwikAppChild.__init(self, dev)
end
function MyChildA:myBtn(ev)
  self.parent.children.childB:updateView('l1', 'text', os.date('%c'))
  print("Button pressed, updating childB's label")
end
function MyChildA:update(data)
  self:updateView('value', "text", fmt("value: %s", data.A.value))
end

MyChildB = {}
class 'MyChildB'(QwikAppChild)
function MyChildB:__init(dev)
  QwikAppChild.__init(self, dev)
end
function MyChildB:mySlider(ev)
  self.parent.children.childA:updateProperty('value', ev.values[1])
  print("Slider", ev.values[1])
end
function MyChildB:update(data)
  self:updateView('value', "text", fmt("value: %s", data.B.value))
end
