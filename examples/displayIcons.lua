-- QA that let you browse and display user icons

--%%name:geticons
--%%type:com.fibaro.genericDevice
--%%mode:online

--%%u:{{button="b1",text="Prev",onReleased="PreviousIcon"},{button="b2",text="Next",onReleased="NextIcon"}}
--%%u:{label='info',text=""}
--%%u:{label='path',text=""}
--%%u:{label='icon',text=""}

-- {"deviceType":"com.fibaro.genericDevice","fileExtension":"png","id":1001,"iconSetName":"User1001"}
-- /assets/userIcons/devices/User<id>/User<id><state>.png

local icons, iconList = {}, {}
local currentIconId = 1
local fmt = string.format

local function getUserIconInfo()
  local ics = api.get("/icons")
  for _,i in ipairs(ics.device) do
    if i.iconSetName:match("User(%d+)") then
      icons[i.id] = i
      iconList[#iconList+1] = i
    end
  end
end

function QuickApp:onInit()
  self:debug("onInit")
  getUserIconInfo()
  self:showIcon()
  for id,info in pairs(icons) do
    --print("ID:", id, "Type:", info.deviceType)
  end
end

function QuickApp:iconNames(info)
  local mapping = self.deviceIconTypeMapping[info.deviceType]
  if not mapping then return {info.iconSetName.."."..info.fileExtension} end
  local icons = {}
  for _,icon in ipairs(mapping.fileNames) do
    local name = icon:gsub("icon",info.iconSetName).."."..info.fileExtension
    icons[#icons+1] = name
  end
  return icons
end

local function makePath(path)
  if _FLUA then return _FLUA.config.url..path 
  else return path end
end

function QuickApp:showIcon()
  local info = iconList[currentIconId]
  local s = fmt("%d, %s, %s", info.id, info.iconSetName, info.deviceType)
  self:updateView("info", "text", s)
  local iconPath = fmt("/assets/userIcons/devices/User%d/", info.id)
  self:updateView("path", "text", iconPath)
  local iconNames = self:iconNames(info) -- Return icon set names depending on device type
  local ics = {}
  for _,name in ipairs(iconNames) do -- create image html for each icon in icon set
    local path = makePath(fmt("%s%s", iconPath, name))
    ics[#ics+1] = fmt("<img src='%s'>", path)
  end
  self:updateView("icon", "text", table.concat(ics, "</br>"))
end

function QuickApp:PreviousIcon()
  self:debug("PreviousIcon")
  currentIconId = currentIconId - 1
  if currentIconId < 1 then
    currentIconId = #iconList
  end
  self:showIcon()
end

function QuickApp:NextIcon()
  self:debug("NextIcon")
  currentIconId = currentIconId + 1
  if currentIconId > #iconList then
    currentIconId = 1
  end
  self:showIcon()
end