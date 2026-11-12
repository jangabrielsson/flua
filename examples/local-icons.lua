--%%name:local-icons-demo
--%%type:com.fibaro.binarySwitch
--%%icons:local-icons/icons
-- Example: a LOCAL icon set. --%%icons:path points at a folder holding the
-- icons in the upload naming (icon.png, icon0.png, icon100.png, ...). The
-- QA's own id becomes its deviceIcon and the web view renders and switches
-- the icons per the value property — no HC3 upload needed.
-- Run with:
--   .venv/bin/flua examples/local-icons.lua --ui
-- The QA flips value 0/100 a few times (watch the icon switch), then exits.
-- --------------- EOH ---------------
function QuickApp:onInit()
  local flips = 0
  local function flip()
    flips = flips + 1
    if flips > 4 then self:exit() return end
    local value = flips % 2 == 1 and 0 or 100
    self:updateProperty("value", value)
    print("value:", value)
    setTimeout(flip, 500)
  end
  flip()
end
