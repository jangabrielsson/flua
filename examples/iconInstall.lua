--%%name:iconInstall-demo
--%%type:com.fibaro.binarySwitch
-- Example: a self-installing icon set. On the FIRST start after a fresh
-- install the QA makes sure its custom icon set exists in the controller's
-- icon library: it downloads its two icons (icon0/icon100 — the binary
-- provider), scans the library's User sets of its own device type for a
-- byte-identical match (the HC3 serves uploaded art byte-identical), and
-- only uploads a new set when nothing matches. The installed set's id is
-- remembered in internalStorage (plugins/<id>/variables — NOT saved when a
-- QA is re-downloaded, so a fresh download re-runs the check; the id must
-- NOT live in a quickAppVariable, which WOULD be saved). On later starts a
-- single cheap liveness check (the stored id still listed in /api/icons)
-- keeps the QA from re-uploading — and if the set was deleted (e.g. via
-- flua --tool icons ui), the QA reinstalls it cleanly. The user's own
-- deviceIcon choice is respected: restarts never touch deviceIcon.
-- Icons: iconInstall/icons/icon0.png (red = off) and icon100.png (green =
-- on). The download URLs default to this repo and can be overridden with
-- the quickAppVariables iconURL0/iconURL100 (the test suite points them at
-- a mock server).
-- Run online:
--   .venv/bin/flua examples/iconInstall.lua
-- --------------- EOH ---------------

local ICON_FILES = { "icon0", "icon100" }   -- the binary provider's files, in order
local ICON_SET_KEY = "installedIconSet"     -- internalStorage key
local LOOPBACK_JSON = "http://127.0.0.1:11111"  -- the controller's local API (JSON; flua online rewrites it to the configured controller)
local ASSET_TREE = "http://127.0.0.1/assets"    -- the public icon assets (port 80)
local GIT_REPO = "https://raw.githubusercontent.com/jangabrielsson/flua/main/examples/iconInstall/icons/"

function QuickApp:iconURLs()
  -- each file's download URL. The quickAppVariable iconURL0/iconURL100 is an
  -- optional override: a full http(s) URL wins verbatim (the test suite
  -- points them at a mock server), a bare file name resolves against the
  -- repo's icon folder, and unset (getVariable returns "", never nil —
  -- "" is truthy, so `x or default` would never fall through) means the
  -- default file in that folder.
  local base = GIT_REPO
  local urls = {}
  for _, file in ipairs(ICON_FILES) do
    local override = self:getVariable("iconURL" .. file:sub(5)) or ""
    if override == "" then
      urls[file] = base .. file .. ".png"
    elseif override:match("^https?://") then
      urls[file] = override
    else
      urls[file] = base .. override
    end
  end
  return urls
end

function QuickApp:storedIconId()
  return tonumber(self:internalStorageGet(ICON_SET_KEY))
end

function QuickApp:saveIconId(id)
  self:internalStorageSet(ICON_SET_KEY, tostring(id), true)
end

function QuickApp:onInit()
  self:ensureIconSet()
end

function QuickApp:ensureIconSet()
  local mode = _FLUA.mode
  if mode ~= "online" and mode ~= "proxy" then
    self:debug("iconInstall: needs an HC3 (online/proxy) — skipping in " .. tostring(mode))
    return
  end
  local stored = self:storedIconId()
  -- the LIVE icon library (JSON via the controller's local API; flua online
  -- rewrites the loopback to the configured HC3) — api.get would answer from
  -- the sim catalog in the emulator, so the loopback keeps one behavior.
  net.HTTPClient():request(LOOPBACK_JSON .. "/api/icons", {
    success = function(response)
      local ok, lib = pcall(json.decode, response.data)
      if not ok or type(lib) ~= "table" then
        self:error("iconInstall: cannot read the icon library")
        return
      end
      local devices = type(lib.device) == "table" and lib.device or {}
      if stored then
        for _, entry in ipairs(devices) do
          if entry.id == stored then
            self:debug("iconInstall: icon set " .. stored .. " already installed — leaving deviceIcon alone")
            return
          end
        end
        self:debug("iconInstall: stored icon set " .. stored .. " is gone — reinstalling")
        self:internalStorageRemove(ICON_SET_KEY)
      end
      local candidates = {}
      for _, entry in ipairs(devices) do
        if entry.deviceType == self.type
          and tostring(entry.iconSetName or ""):match("^User%d+$") then
          candidates[#candidates + 1] = entry
        end
      end
      self:downloadIcons(function(icons)
        self:findMatchingSet(candidates, icons, function(foundId)
          if foundId then
            self:saveIconId(foundId)
            self:updateProperty("deviceIcon", foundId)
            self:debug("iconInstall: found existing icon set " .. foundId)
          else
            self:uploadIcons(icons)
          end
        end)
      end)
    end,
    error = function(err)
      self:error("iconInstall: cannot reach the icon library: " .. tostring(err))
    end,
  })
end

function QuickApp:downloadIcons(cb)
  local urls = self:iconURLs()
  local icons, pending = {}, #ICON_FILES
  for _, file in ipairs(ICON_FILES) do
    net.HTTPClient():request(urls[file], {
      success = function(response)
        icons[file] = response.data
        pending = pending - 1
        if pending == 0 then cb(icons) end
      end,
      error = function(err)
        self:error("iconInstall: cannot download " .. urls[file] .. ": " .. tostring(err))
      end,
    })
  end
end

function QuickApp:findMatchingSet(candidates, icons, cb)
  local index = 0
  local function nextCandidate()
    index = index + 1
    local entry = candidates[index]
    if not entry then cb(nil) return end
    local set = entry.iconSetName
    local ext = entry.fileExtension or "png"
    local fetched, pending = {}, #ICON_FILES
    for _, file in ipairs(ICON_FILES) do
      -- the asset tree serves the set's states as <set><state>.<ext>;
      -- icon0 -> state 0, icon100 -> state 100
      local url = ASSET_TREE .. "/userIcons/devices/" .. set .. "/"
        .. set .. file:sub(5) .. "." .. ext
      net.HTTPClient():request(url, {
        success = function(response)
          fetched[file] = response.data
          pending = pending - 1
          if pending == 0 then
            if fetched.icon0 == icons.icon0 and fetched.icon100 == icons.icon100 then
              cb(entry.id)
            else
              nextCandidate()
            end
          end
        end,
        error = function()
          pending = pending - 1
          if pending == 0 then nextCandidate() end
        end,
      })
    end
  end
  nextCandidate()
end

function QuickApp:uploadIcons(icons)
  local provider = QuickApp.deviceIconTypeMapping[self.type]
  if not provider then
    self:error("iconInstall: no icon provider for " .. tostring(self.type))
    return
  end
  local files = {}
  for i, file in ipairs(ICON_FILES) do
    files[i] = icons[file]
  end
  -- the HC3's standard upload (POST 127.0.0.1:11111/api/icons multipart);
  -- flua online rewrites the loopback to the configured controller
  self:uploadIconFiles({
    fileNames = provider.fileNames,
    files = files,
    deviceType = self.type,
  }, {}, function(iconId)
    self:saveIconId(iconId)
    self:updateProperty("deviceIcon", iconId)
    self:debug("iconInstall: uploaded new icon set " .. iconId)
  end, function(err)
    self:error("iconInstall: icon upload failed: " .. tostring(err))
  end)
end
