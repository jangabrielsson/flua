--%%name:ui-interaction-suite
--%%type:com.fibaro.binarySwitch
--%%u:{button="btnA",text="A",onReleased="act"}
--%%u:{button="btnB",text="B",onReleased="act"}
--%%u:{button="btnC",text="C",onReleased="act"}
--%%u:{label="lbl",text=""}
-- Data-driven UI interaction suite: one table of cases, one loop — every
-- button/select/slider of a whole UI covered in one run, exit code = the
-- failure count. The single-action pattern this scales is
-- examples/ui-interaction-test.lua.
--
--   .venv/bin/flua --api local examples/ui-interaction-suite.lua
--
-- Add rows for every element: {element, event, value?, expect}. The
-- expect value is what the callback should leave in the label — a proxy
-- for "the right callback ran with the right input"; for real QAs assert
-- the actual state (properties, variables, view text) instead.

local cases = {
  {element="btnA", event="onReleased", expect="A"},
  {element="btnB", event="onReleased", expect="B"},
  {element="btnC", event="onReleased", expect="C"},
}
local failures = 0

-- The rendered text of one element in the current viewLayout ($jason tree).
local function viewText(view, name)
  local body = (view or {})["$jason"] and view["$jason"].body
  local items = body and body.sections and body.sections.items
  for _, row in ipairs(items or {}) do
    for _, c in ipairs(row.components or {}) do
      if c.name == name then return c.text end
    end
  end
end

function QuickApp:act(e)
  -- the mapped callback: record which button fired
  self:updateView("lbl", "text", tostring(e.elementName):gsub("btn", ""))
end

function QuickApp:nextCase()
  local case = table.remove(cases, 1)
  if not case then
    -- exit() is asynchronous: a poll timer already in flight can arrive
    -- after the verdict — finish once, ignore the stragglers
    if not self.done then
      self.done = true
      print(failures == 0 and "VERDICT: all passed" or ("VERDICT: " .. failures .. " failed"))
      exit(failures)
    end
    return
  end
  _FLUA.uiEvent(case.element, case.event, case.value)
  -- the callback fires asynchronously AFTER uiEvent returns: poll for its
  -- effect, then assert (bounded, works in every clock mode)
  local tries = 0
  local function poll()
    tries = tries + 1
    local text = viewText(self:getView(), "lbl")
    if text == case.expect then
      print("PASS " .. case.element .. " -> " .. text)
      self:nextCase()
    elseif tries >= 50 then
      failures = failures + 1
      print("FAIL " .. case.element .. " — expected " .. case.expect .. ", got " .. tostring(text))
      self:nextCase()
    else
      setTimeout(poll, 10)
    end
  end
  setTimeout(poll, 10)
end

function QuickApp:onInit()
  self:nextCase()
end
