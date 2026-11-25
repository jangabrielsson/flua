--%%name:ui divider
--%%type:com.fibaro.genericDevice
--%%useUiView:false

-- The HC3's horizontal divider: a space element with classes={'borderTop'}
-- renders the app's grey .spacer-line — a v2 (uiView) feature: with
-- useUiView:false the legacy renderer draws no line (live-tested 5.221).
-- The main QA's --%%u rows show it inline; the child's --%%rsrc uiView
-- shows it in the dialog, plus a tinted button and a blank gap.

--%%u:{label='topLbl',text='Above the line',textAlign='center'}
--%%u:{space='div1',classes={'borderTop'}}
--%%u:{label='midLbl',text='Between two lines',textAlign='center'}
--%%u:{space='div2',classes={'borderTop'}}
--%%u:{label='bottomLbl',text='Below the line',textAlign='center'}

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
