--https://github.com/LuaLS/lua-language-server/wiki/Annotations

---@meta

---The HC3 REST API surface (hybrid sim/HC3 dispatch in flua).
---Each call returns (data, status); data is nil on failures.
---@class api
---@field get fun(url: string, body?: any): any, number
---@field post fun(url: string, body?: any): any, number
---@field put fun(url: string, body?: any): any, number
---@field delete fun(url: string, body?: any): any, number
---@field hc3 api_hc3 Direct calls to the real HC3 (bypasses the hybrid dispatch)
api = {}

---@class api_hc3
---@field get fun(url: string, body?: any): any, number
---@field post fun(url: string, body?: any): any, number
---@field put fun(url: string, body?: any): any, number
---@field delete fun(url: string, body?: any): any, number
api_hc3 = {}

---@class json
---@field encode fun(value: any): string
---@field decode fun(text: string): any
json = {}
