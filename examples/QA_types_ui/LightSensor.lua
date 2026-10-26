--%%name:LightSensor
--%%type:com.fibaro.lightSensor

function QuickApp:onInit()
    self:debug(self.name,self.id)
    if not api.get("/devices/"..self.id).enabled then
        self:debug(self.name,self.id,"Device is disabled")
        return
    end

    self:updateProperty("value", math.pi)
    self:updateProperty("batteryLevel",75)
end 