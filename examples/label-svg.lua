--%%name:label svg demo
--%%type:com.fibaro.genericDevice
-- (deliberately v1 — NO --%%useUiView. The label-HTML route for inline SVG
-- art is the known-good HC3 pattern and it renders only in the legacy v1
-- view (live-verified 5.221); in uiView/v2 it shows a placeholder. v2 QAs
-- serve their art over http(s) instead. Run with:
--   .venv/bin/flua --ui 8090 examples/label-svg.lua)

--%%u:{label="svgLabel",text="svg appears here"}

-- Lightweight Base64 encoder (no external libs)
local b = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
local function encodeBase64(data)
  return ((data:gsub('.', function(x)
    local r, b_val = '', x:byte()
    for i = 8, 1, -1 do r = r .. (b_val % 2^i - b_val % 2^(i-1) > 0 and '1' or '0') end
    return r
  end) .. '0000'):gsub('%d%d%d?%d?%d?%d?', function(x)
    if (#x < 6) then return '' end
    local c = 0
    for i = 1, 6 do c = c + (x:sub(i, i) == '1' and 2^(6-i) or 0) end
    return b:sub(c + 1, c + 1)
  end) .. ({ '', '==', '=' })[#data % 3 + 1])
end

function QuickApp:onInit()
  _FLUA.keepAlive()
  self:debug("label svg demo ready")
  -- the SVG (must include the xmlns attribute), base64-encoded, wrapped in
  -- an <img> tag, and set as the label's HTML text
  local svg = [[
    <svg xmlns="http://www.w3.org/2000/svg" width="120" height="48">
      <rect width="120" height="48" rx="10" fill="#2563eb"/>
      <text x="60" y="31" font-family="Arial" font-size="18" fill="white" text-anchor="middle">flua</text>
    </svg>
  ]]
  local base64Svg = encodeBase64(svg)
  self:updateView("svgLabel", "text",
    string.format('<img src="data:image/svg+xml;base64,%s" />', base64Svg))
end
