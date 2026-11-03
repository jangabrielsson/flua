--%%name:AlarmPanel
--%%type:com.fibaro.genericDevice
--%%description:"Alarm system control panel (bundled with flua)"

-- The alarm system's control panel: a UI over the /alarms/v1/* endpoints
-- (load the alarmEndpoint device alongside it, or use the sim's built-in
-- partitions alone):
--   local endpoint = _FLUA.loadSimDevice("alarmEndpoint")
--   local panel = _FLUA.loadSimDevice("alarmPanel")
--
-- A select lists the current partitions (built-in, deployed
-- com.fibaro.alarmPartition QAs, created ones); the info label shows the
-- selected partition's state, the Arm/Disarm buttons drive the endpoints.
-- The panel refreshes itself from the refreshState feed, so partitions
-- appearing/vanishing and state changes (however they happen) update the UI.

--%%u:{label='Partition',text='Partition'}
--%%u:{select='partition',text='Select partition',onToggled='picked',options={}}
--%%u:{label='lblInfo',text='no partitions'}
--%%u:{{button='btnArm',text='Arm',onReleased='arm'},{button='btnDisarm',text='Disarm',onReleased='disarm'}}

function QuickApp:onInit()
  self:debug("alarm panel up, id", self.id)
  self.current = nil
  self:refresh()
  local sub = RefreshStateSubscriber()
  sub:subscribe(
    function(e)
      local t = e.type or ""
      return t == "DeviceCreatedEvent"
        or t == "DeviceRemovedEvent"
        or t == "AlarmPartitionArmedEvent"
        or t == "AlarmPartitionBreachedEvent"
        or t == "AlarmPartitionModifiedEvent"
        or (
          t == "DevicePropertyUpdatedEvent"
          and (e.data and (e.data.property == "armed" or e.data.property == "alarm"))
        )
    end,
    function() self:refresh() end
  )
  sub:run()
  _FLUA.keepAlive()
end

-- rebuild the select options + the state label from the endpoint
function QuickApp:refresh()
  local parts, status = api.get("/alarms/v1/partitions")
  if status ~= 200 then
    self:updateView("lblInfo", "text", "alarm endpoints unavailable")
    return
  end
  local options = {}
  for _, p in ipairs(parts) do
    options[#options + 1] = { type = "option", text = p.name, value = tostring(p.id) }
  end
  -- keep the current selection when it still exists, else pick the first
  local found = false
  for _, p in ipairs(parts) do
    if tostring(p.id) == tostring(self.current) then found = true end
  end
  if not found then
    self.current = parts[1] and parts[1].id or nil
  end
  self:updateView("partition", "options", options)
  if self.current then
    self:updateView("partition", "selectedItem", tostring(self.current))
  end
  local selected
  for _, p in ipairs(parts) do
    if tostring(p.id) == tostring(self.current) then selected = p end
  end
  if selected then
    local state = selected.breached and "BREACHED" or (selected.armed and "armed" or "disarmed")
    local color = selected.breached and "orange" or (selected.armed and "green" or "red")
    self:updateView(
      "lblInfo",
      "text",
      "<font color='" .. color .. "'>" .. selected.name .. " (id " .. selected.id
        .. ") — " .. state .. "</font>"
    )
  else
    self:updateView("lblInfo", "text", "no partitions")
  end
end

function QuickApp:picked(event)
  self.current = tonumber(event.values and event.values[1])
  self:refresh()
end

function QuickApp:arm()
  if not self.current then
    self:warning("no partition selected")
    return
  end
  local _, status = api.post("/alarms/v1/partitions/" .. self.current .. "/actions/arm")
  if status ~= 202 then
    self:warning("arm failed:", status)
  end
  self:refresh()
end

function QuickApp:disarm()
  if not self.current then
    self:warning("no partition selected")
    return
  end
  local _, status = api.delete("/alarms/v1/partitions/" .. self.current .. "/actions/disarm")
  if status ~= 202 then
    self:warning("disarm failed:", status)
  end
  self:refresh()
end
