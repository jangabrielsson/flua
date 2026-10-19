--%%name:Scenes example
-- flua scenes, self-tested: a driver QA creates a base device, loads an
-- HC3 Lua scene (--%%scene:true) from an inline string, triggers it by
-- flipping the device, and checks the effect the scene's actions had.
--
-- Run: flua examples/scenes.lua            (offline, exits with the failure count)

function QuickApp:onInit()
  local failures = 0
  local function pass(msg) print("PASS: " .. msg) end
  local function fail(msg)
    failures = failures + 1
    print("FAIL: " .. msg)
  end

  -- the scene's actions signal through a global variable (must exist first:
  -- the HC3 404s a PUT on a missing one)
  api.post("/globalVariables", { name = "sceneRuns", value = "no" })

  -- a base device for the scene to watch
  local dev = api.post("/devices", {
    name = "Example lamp",
    type = "com.fibaro.binarySwitch",
    properties = { value = false },
  })
  local lampId = dev.id

  -- the scene: a device trigger + top-level actions below the marker
  local sceneCode = ([=[
COND = {
  operator = "any",
  conditions = {
    { type = "device", id = LAMP_ID, property = "value",
      operator = "==", value = true, isTrigger = true },
  }
}
-- ===== SCENE ACTIONS =====
fibaro.setGlobalVariable("sceneRuns", "on")
print("SCENE_RAN", _sceneId, sourceTrigger.type, sourceTrigger.id)
]=]):gsub("LAMP_ID", tostring(lampId))

  local sceneId, err = _FLUA.loadQAfromString(sceneCode, {
    "scene:true", "name:ExampleScene",
  })
  if not sceneId then fail("load scene: " .. tostring(err)) exit(1) return end

  -- the scene must answer /scenes
  local scenes = api.get("/scenes")
  for _, s in ipairs(scenes) do
    if s.id == sceneId then pass("scene in /scenes") end
  end

  local function gv() return api.get("/globalVariables/sceneRuns").value end

  local function waitFor(what, untilTrue, deadline, done)
    if untilTrue() then pass(what) done() return end
    if os.time() > deadline then fail(what) done() return end
    setTimeout(function() waitFor(what, untilTrue, deadline, done) end, 50)
  end

  local function finish()
    print("failures:", failures)
    exit(failures > 0 and 1 or 0)
  end

  -- 1. the device trigger: flipping the lamp runs the scene
  api.put("/devices/" .. lampId, { properties = { value = true } })
  waitFor("device trigger ran the scene", function() return gv() == "on" end,
    os.time() + 5, function()
    -- 2. manual execute also works (sourceTrigger = manual)
    api.put("/globalVariables/sceneRuns", { value = "no" })
    api.post("/scenes/" .. sceneId .. "/execute", nil)
    waitFor("manual execute ran the scene", function() return gv() == "on" end,
      os.time() + 5, finish)
  end)
end
