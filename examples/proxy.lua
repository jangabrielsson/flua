--%%name:Ptest
--%%type:com.fibaro.binarySwitch

--%%u:{label="l1",text="Label text2"}
--%%u:{button="B1",text="Press me",onReleased="fopp"}
--%%u:{slider="s1",text="Slider",min="0",max="100",value="50",onChanged="slider"}
--%%u:{select='sel1',text='Select an option',onToggled='selectChanged',value='11',options={{type='option',text='Option 1',value='11'},{type='option',text='Option 2',value='12'}}}
--%%u:{multi='m1',text='Select an option',onToggled='multiChanged',values={'11'},options={{type='option',text='Option 1',value='11'},{type='option',text='Option 2',value='12'}}}

--%%mode:proxy

function QuickApp:onInit()
  print("Proxy test initialized")
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