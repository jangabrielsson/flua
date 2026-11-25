--%%name:ui divider
--%%type:com.fibaro.genericDevice
--%%useUiView:true

-- The HC3's horizontal divider: a space element with classes={'borderTop'}
-- renders the app's grey .spacer-line in the uiView. A space without the
-- class is a blank gap. Live-tested 5.221. Run it and open the viewer:
-- the child's UI shows the labels, two divider lines, and a tinted button.

--%%rsrc:uiDivider:{{label='topLbl',text='Above the line',textAlign='center'}}
--%%rsrc:uiDivider:{space='div1',classes={'borderTop'}}
--%%rsrc:uiDivider:{{label='midLbl',text='Between two lines',textAlign='center'}}
--%%rsrc:uiDivider:{space='div2',classes={'borderTop'}}
--%%rsrc:uiDivider:{{button='okBtn',text='OK',onReleased='press',color='#2e9e5b'}}
--%%rsrc:uiDivider:{space='gap'}

Child = {}
class "Child"(QuickAppChild)
function Child:__init(dev) QuickAppChild.__init(self, dev) end
function Child:press() self:debug("pressed") end

function QuickApp:onInit()
  if _FLUA then _FLUA.keepAlive() end
  self:createChildDevice({
    name = "Divided child",
    type = "com.fibaro.binarySensor",
    initialProperties = { uiView = fibaro.RSRC.uiDivider },
  }, Child)
end
