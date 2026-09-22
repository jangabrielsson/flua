--%%name:UI test
--%%type:com.fibaro.binarySwitch

--%%u:{label="l1",text="Label text"}
--%%u:{button="B1",text="Press me",onReleased="fopp"}
--%%u:{slider="s1",text="Slider",min="0",max="100",value="50",onChanged="slider"}
--%%u:{select='sel1',text='Select an option',onToggled='selectChanged',value='11',options={{type='option',text='Option 1',value='11'},{type='option',text='Option 2',value='12'}}}
--%%u:{multi='m1',text='Select an option',onToggled='multiChanged',values={'11'},options={{type='option',text='Option 1',value='11'},{type='option',text='Option 2',value='12'}}}

function QuickApp:onInit()
  print("UI test initialized")
  setTimeout(function()
    -- simulate a press on the B1 button the way the HC3 UI would deliver it:
    -- through the API endpoint (self:UIAction(...) is the in-QA equivalent)
    api.get("/plugins/callUIEvent?deviceID=" .. self.id .. "&elementName=B1&eventType=onReleased")
    api.get("/plugins/callUIEvent?deviceID=" .. self.id .. "&elementName=s1&eventType=onChanged&value=42")
    api.get("/plugins/callUIEvent?deviceID=" .. self.id .. "&elementName=sel1&eventType=onToggled&value=12")
    api.get("/plugins/callUIEvent?deviceID=" .. self.id .. "&elementName=m1&eventType=onToggled&value=12")
  end, 1000)
end

function QuickApp:fopp()
  print("Button released")
end

function QuickApp:slider(e)
  print("Slider changed to", e.values and e.values[1])
end

function QuickApp:selectChanged(e)
  print("Select changed to", e.values and e.values[1])
end

function QuickApp:multiChanged(e)
  print("Multi changed to", e.values and json.encode(e.values))
end