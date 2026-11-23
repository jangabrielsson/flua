--%%name:ui probe
--%%type:com.fibaro.genericDevice
--%%useUiView:true
-- (v2 elements render only from uiView on the real HC3 — live-verified for
-- tabView and collapsible; NOT editable in the HC3 UI editor: keep
-- flua-authored)

-- Upload-test QA for the HC3 app (5.221). Live-verified results:
--   1. the network image (a public placeholder URL) -> renders.
--   2. the collapsible "Favorites" -> renders; tap it to expand/collapse,
--      and the Play button inside logs "PLAY" (Debug console).
--   3. the image element with a BASE64 data URI -> question-mark
--      placeholder (the app's image component renders NO data URIs,
--      utf8 or base64).
--   4. the label-HTML route (base64 <img> in the label text) -> renders
--      only in the legacy v1 view (useUiView false); in uiView/v2 it
--      does not. This QA is v2, so both SVG rows are placeholders on the
--      app — they render in flua's viewer.
-- Run locally with:
--   .venv/bin/flua --ui 8090 examples/ui-probe.lua
-- Upload with:
--   .venv/bin/flua --tool uploadQA examples/ui-probe.lua
--%%u:{image="svgBadge",url=""}
--%%u:{image="netImage",url="https://placehold.co/120x48?text=net"}
--%%u:{label="svgLabel",text="svg appears here"}
--%%u:{collapsible="favs",text="Favorites",collapsed=false,components={
--  {{label="lbl",text="Tap the header to collapse"}},
--  {{button="play",text="Play",onReleased="play"}}
--}}

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
  if _FLUA then _FLUA.keepAlive() end
  self:debug("ui probe ready")
  -- 1. the SVG (must include the xmlns attribute)
  local svg = [[
    <svg xmlns="http://www.w3.org/2000/svg" width="120" height="48">
      <rect width="120" height="48" rx="10" fill="#2563eb"/>
      <text x="60" y="31" font-family="Arial" font-size="18" fill="white" text-anchor="middle">flua</text>
    </svg>
  ]]
  local base64Svg = encodeBase64(svg)
  -- 2. image element: a base64 data URI (the open question on the HC3 app)
  self:updateView("svgBadge", "url", "data:image/svg+xml;base64," .. base64Svg)
  -- 3. label element: the same SVG as base64 inside the label's HTML
  --    (the known-good HC3 pattern for inline art)
  self:updateView("svgLabel", "text",
    string.format('<img src="data:image/svg+xml;base64,%s" />', base64Svg))
end

function QuickApp:play()
  print("PLAY")
end
