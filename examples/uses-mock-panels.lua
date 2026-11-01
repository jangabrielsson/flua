--%%name:uses-mock-panels
-- A QA exercising the endpoints its emulation module registers — the
-- self-contained pattern for panels the sim does not implement. Run:
--   .venv/bin/flua --api local examples/uses-mock-panels.lua

function QuickApp:onInit()
  require("mock-panels")
  setTimeout(function()
    local panel, s = api.get("/panels/sprinklers/7?zone=2")
    print("GET", s, json.encode(panel))
    local run, s2 = api.post("/panels/sprinklers/7/actions/run", { minutes = 10 })
    print("POST", s2, json.encode(run))
    local ok = s == 200 and panel.name == "Sprinklers 7" and s2 == 200 and run.started == true
    print(ok and "VERDICT: all passed" or "VERDICT: failed")
    exit(ok and 0 or 1)
  end, 20)
end
