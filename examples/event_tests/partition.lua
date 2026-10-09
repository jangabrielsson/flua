--%%name:AlarmPartition
--%%type:com.fibaro.alarmPartition


function QuickApp:onInit()
    self:debug("Initialized alarm partition")
end

function QuickApp:arm()
    self:debug("alarm partition armed")
    self:updateProperty("armed", true)
    _FLUA.postRefreshEvent({type='AlarmPartitionArmedEvent',data={partitionId=self.id, armed=true}})
end

function QuickApp:disarm()
    self:debug("alarm partition disarmed")
    self:updateProperty("armed", false)    
    _FLUA.postRefreshEvent({type='AlarmPartitionArmedEvent',data={partitionId=self.id, armed=false}})
end 

function QuickApp:breached(state)
    self:debug("alarm partition breached: " .. tostring(state))
    self:updateProperty("alarm", state)    
    _FLUA.postRefreshEvent({type='AlarmPartitionBreachedEvent',data={partitionId=self.id, breached=state}})
end 
