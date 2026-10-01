--%%name:files
--%%type:com.fibaro.binarySwitch
--%%warn:true

-- Demonstrates how to list and read files associated with the QuickApp

function QuickApp:onInit()
  local files = api.get("/quickApp/"..self.id.."/files")
  assert(type(files) == "table", "Expected files to be a table")
  for _,f in ipairs(files) do
    print(f.name)
  end

  local file = api.get("/quickApp/"..self.id.."/files/"..files[1].name)
  print(file.content)
end
