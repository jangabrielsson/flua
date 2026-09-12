--%%name:http-demo
-- Example: net.HTTPClient — asynchronous HTTP from inside a QA.
-- Run with:
--   .venv/bin/flua examples/http.lua
--
-- Needs internet access (httpbin.org). If httpbin is down, the error
-- callbacks print cleanly instead of crashing — https://httpbingo.org is a
-- good drop-in replacement.
setTimeout(function()
  local client = net.HTTPClient()

  -- GET with a success/error pair
  client:request("https://httpbin.org/get?hello=world", {
    options = { timeout = 5 },
    success = function(resp)
      print("get:", resp.status, resp.headers["Content-Type"])
      print("get data:", resp.data:sub(1, 80))
    end,
    error = function(err) print("get error:", err) end,
  })

  -- POST with headers and a body
  client:request("https://httpbin.org/post", {
    options = {
      method = "POST",
      headers = { ["Content-Type"] = "application/json", ["X-Flua"] = "demo" },
      data = '{"value": 42}',
      timeout = 5,
    },
    success = function(resp)
      print("post:", resp.status)
      print("post data:", resp.data:sub(1, 120))
    end,
    error = function(err) print("post error:", err) end,
  })

  -- Transport failures reach the error callback, never success
  client:request("http://127.0.0.1:1/", {
    success = function(resp) print("refused: SHOULD NOT HAPPEN") end,
    error = function(err) print("refused:", err) end,
  })
end, 100)
