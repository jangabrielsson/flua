--%%name:multifile-demo
--%%file:multifile/lib.lua,lib
-- Example: multi-file QAs. Extra files declared with --%%file:path,name load
-- into the QA in declaration order BEFORE this main file, so helpers defined
-- there are available below.
-- Run with:
--   .venv/bin/flua examples/multifile.lua
-- --------------- EOH ---------------
function QuickApp:onInit()
  print("helper says:", helper())

  local files = api.get("/quickApp/"..self.id.."/files")
  for _,f in ipairs(files) do
    print("file:", f.name)
  end
end
