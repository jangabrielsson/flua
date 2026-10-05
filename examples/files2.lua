--%%name:files2
--%%type:com.fibaro.binarySwitch
--%%warn:true

-- Demonstrates how to add file to quickapp dynamically at runtime

function QuickApp:onInit()
  if not FOO then
  api.post("/quickApp/"..self.id.."/files", {
    name = "newfile.txt",
    content = "FOO = 42 -- global variable"
  })
else
  print("FOO=",FOO)
end
end
