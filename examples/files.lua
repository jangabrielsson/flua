--%%name:files
--%%type:com.fibaro.binarySwitch
--%%warn:true

function QuickApp:onInit()
  local files = api.get("/quickApp/"..self.id.."/files")
  assert(type(files) == "table", "Expected files to be a table")
  for _,f in ipairs(files) do
    print(f.name)
  end

  local file = api.get("/quickApp/"..self.id.."/files/"..files[1].name)
  print(file.content)
end
