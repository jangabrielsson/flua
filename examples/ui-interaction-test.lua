--%%name:ui-interaction-test
--%%type:com.fibaro.binarySwitch
--%%u:{button="btnMode",text="Mode",onReleased="cycleMode"}
--%%u:{label="lblMode",text="auto"}
--%%u:{select="selZone",text="Zone",onToggled="pickZone",value="11",options={{type='option',text='Auto',value='11'},{type='option',text='Manual',value='12'}}}
--%%var:fixture="examples/ui-fixture.json"
-- Self-asserting UI interaction test: the "from it starts to
-- assertion-backed" pattern. Loads a JSON fixture, injects UI events the
-- way the HC3 UI would deliver them, WAITS for the asynchronous callback,
-- asserts both the rendered view and the simulator state, and exits with
-- the failure count as the verdict.
--
-- Run from the repo root:
--   .venv/bin/flua --api local examples/ui-interaction-test.lua
-- Pin the clock for time-dependent fixtures (os.date schedules etc.):
--   .venv/bin/flua --start 2027-01-04 examples/ui-interaction-test.lua
--
-- Fixture paths are PROCESS-CWD-relative (io.open does not resolve against
-- the QA file): the default above works when flua starts in the repo root;
-- from anywhere else pass an absolute path:
--   flua -D 'var:fixture="/abs/path/ui-fixture.json"' examples/ui-interaction-test.lua
-- The onInit loader errors with that explanation if the file is missing.

local failures = 0
local function check(name, ok, detail)
  if ok then
    print("PASS " .. name)
  else
    failures = failures + 1
    print("FAIL " .. name .. (detail and (" — " .. tostring(detail)) or ""))
  end
end

-- Poll until the condition holds (callbacks fire asynchronously AFTER
-- uiEvent returns); maxTries bounds it in every clock mode.
local function waitUntil(cond, thenFn, maxTries)
  maxTries = maxTries or 100
  local tries = 0
  local function poll()
    tries = tries + 1
    if cond() then
      thenFn()
    elseif tries < maxTries then
      setTimeout(poll, 10)
    else
      thenFn()  -- timeout: the step's assertions report the failure
    end
  end
  setTimeout(poll, 10)
end

-- The rendered text of one element in the current viewLayout
-- (getView returns the legacy $jason view tree).
local function viewText(view, name)
  local body = (view or {})["$jason"] and view["$jason"].body
  local items = body and body.sections and body.sections.items
  for _, row in ipairs(items or {}) do
    for _, c in ipairs(row.components or {}) do
      if c.name == name then return c.text end
    end
  end
end

function QuickApp:onInit()
  local fixture = self:getVariable("fixture")
  local f = io.open(fixture)
  if not f then
    error(
      "cannot open fixture '"
        .. fixture
        .. "' — io.open resolves against the process CWD, not the QA file;"
        .. " run flua from the fixture's directory or pass an absolute path"
        .. " via -D 'var:fixture=/abs/path/...'"
    )
  end
  self.fixture = json.decode(f:read("a"))
  f:close()

  self.mode = "auto"
  self.zone = self.fixture.zone or "11"
  self:updateView("lblMode", "text", self.mode)

  -- step 1: fixture + initial render
  check("fixture loaded", self.fixture.zone == "11", self.fixture.zone)
  check("initial view", viewText(self:getView(), "lblMode") == "auto")

  -- step 2: press the button; the mapped callback runs asynchronously —
  -- wait for its effect before asserting
  _FLUA.uiEvent("btnMode", "onReleased")
  waitUntil(
    function() return viewText(self:getView(), "lblMode") == "manual" end,
    function()
      check("button changed the view", viewText(self:getView(), "lblMode") == "manual")
      check("button updated the device state", self.properties.value == true)
      local dev = api.get("/devices/" .. self.id)
      check("state visible through the sim API", dev.properties.value == true)

      -- step 3: change the select (chained, so the steps run in order);
      -- values arrive as strings
      _FLUA.uiEvent("selZone", "onToggled", "12")
      waitUntil(
        function() return self.zone == "12" end,
        function()
          check("select delivered its value", self.zone == "12")
          self:updateView("lblMode", "text", self.zone == "11" and "auto" or "manual")
          check(
            "view after the select",
            viewText(self:getView(), "lblMode") == "manual"
          )
          self:finish()
        end
      )
    end
  )
end

function QuickApp:finish()
  print(failures == 0 and "VERDICT: all checks passed" or ("VERDICT: " .. failures .. " check(s) failed"))
  exit(failures)
end

function QuickApp:cycleMode()
  self.mode = self.mode == "auto" and "manual" or "auto"
  self:updateView("lblMode", "text", self.mode)
  self:updateProperty("value", true)
end

function QuickApp:pickZone(e)
  self.zone = e.values and e.values[1]
end
