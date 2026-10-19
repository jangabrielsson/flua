"""net.*Server (flua extension): mock servers hosted by a QA.

Each test drives one server kind from the QA's own net.* clients — the same
pattern an agent uses without the repo. QAs assert and exit with the failure
count; the tests check the exit code and the PASS/FAIL lines.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_qa(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "net-server-test.lua"
    script.write_text(source)
    return subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_mock_server_example_self_tests() -> None:
    # examples/mockServer.lua is the living fixture: all four server kinds
    # exercised from the QA's own clients, exit code = failure count
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/mockServer.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for line in ("http status", "http body", "http header", "tcp reply", "udp reply", "ws reply"):
        assert f"PASS: {line}" in result.stdout
    assert "failures: 0" in result.stdout


def test_require_loads_sibling_test_libs(tmp_path) -> None:
    # the agent pattern: mock servers (and other test scaffolding) live in a
    # sibling file loaded with require() — runtime-only, never part of the
    # .fqa package (only --%%file files ship)
    lib = tmp_path / "mocklib.lua"
    lib.write_text(
        "local M = {}\n"
        "function M.upper(data) return data:upper() end\n"
        "return M\n"
    )
    result = run_qa(
        tmp_path,
        "--%%name:req_srv\n"
        "function QuickApp:onInit()\n"
        "  local lib = require('mocklib')\n"
        "  local srv = net.TCPServer()\n"
        "  srv:listen(0, lib.upper)\n"
        "  local c = net.TCPSocket({timeout=5000})\n"
        "  c:connect('127.0.0.1', srv.port, {\n"
        "    success = function()\n"
        "      c:send('hi', {\n"
        "        success = function()\n"
        "          c:read({\n"
        "            success = function(d)\n"
        "              print('GOT', d)\n"
        "              exit(d == 'HI' and 0 or 1)\n"
        "            end,\n"
        "            error = function(e) print('ERR', e); exit(1) end,\n"
        "          })\n"
        "        end,\n"
        "        error = function(e) print('ERR', e); exit(1) end,\n"
        "      })\n"
        "    end,\n"
        "    error = function(e) print('ERR', e); exit(1) end,\n"
        "  })\n"
        "end\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GOT HI" in result.stdout


def test_require_module_sees_qa_globals(tmp_path) -> None:
    # a required sibling file loads INTO the QA's environment (like a
    # --%%file): the module can use net/fibaro/setInterval directly —
    # including hosting a mock server — and returns a per-QA cached table
    lib = tmp_path / "serverlib.lua"
    lib.write_text(
        "local M = {}\n"
        "M.sawNet = type(net.TCPServer) == 'table'\n"
        "M.sawFibaro = type(fibaro) == 'table'\n"
        "M.sawSetInterval = type(setInterval) == 'function'\n"
        "function M.start(handler)\n"
        "  local srv = net.TCPServer()\n"
        "  srv:listen(0, handler)\n"
        "  return srv\n"
        "end\n"
        "return M\n"
    )
    result = run_qa(
        tmp_path,
        "--%%name:req_env\n"
        "function QuickApp:onInit()\n"
        "  if require then require('serverlib') end  -- guarded: no-op on the HC3\n"
        "  local M = require('serverlib')\n"
        "  print('GLOBALS', M.sawNet, M.sawFibaro, M.sawSetInterval)\n"
        "  local srv = M.start(function(data) return data:upper() end)\n"
        "  local c = net.TCPSocket({timeout=5000})\n"
        "  c:connect('127.0.0.1', srv.port, {\n"
        "    success = function()\n"
        "      c:send('hi', {\n"
        "        success = function()\n"
        "          c:read({\n"
        "            success = function(d)\n"
        "              print('GOT', d)\n"
        "              local again = require('serverlib') == M\n"
        "              print('CACHED', again)\n"
        "              exit(d == 'HI' and again and 0 or 1)\n"
        "            end,\n"
        "            error = function(e) print('ERR', e); exit(1) end,\n"
        "          })\n"
        "        end,\n"
        "        error = function(e) print('ERR', e); exit(1) end,\n"
        "      })\n"
        "    end,\n"
        "    error = function(e) print('ERR', e); exit(1) end,\n"
        "  })\n"
        "end\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GLOBALS true true true" in result.stdout
    assert "GOT HI" in result.stdout
    assert "CACHED true" in result.stdout


def test_http_server_contract(tmp_path) -> None:
    # handler request fields, status/body/headers replies, string reply
    # (200 text/plain), nil reply (204), and an unknown route (404)
    eq = (
        "  local function eq(a, b, msg)\n"
        "    if tostring(a) ~= tostring(b) then\n"
        "      failures = failures + 1\n"
        "      print('FAIL: ' .. msg .. ' ' .. tostring(a) .. '!=' .. tostring(b))\n"
        "    end\n"
        "  end\n"
    )
    result = run_qa(
        tmp_path,
        "--%%name:http_srv\n"
        "function QuickApp:onInit()\n"
        "  local failures = 0\n"
        + eq
        + "  local srv = net.HTTPServer()\n"
        "  srv:listen(0, function(req)\n"
        "    if req.url == '/json' then\n"
        "      return {status=201, body={ok=true}, headers={['X-Mock']='1'}}\n"
        "    end\n"
        "    if req.url == '/plain' then return 'hello' end\n"
        "    if req.url == '/empty' then return nil end\n"
        "    return {status=404, body='missing'}\n"
        "  end)\n"
        "  local function get(path, cb)\n"
        "    net.HTTPClient():request('http://127.0.0.1:' .. srv.port .. path, {\n"
        "      success = cb,\n"
        "      error = function(err)\n"
        "        failures = failures + 1\n"
        "        print('FAIL: ' .. tostring(err))\n"
        "      end,\n"
        "    })\n"
        "  end\n"
        "  local n = 0\n"
        "  local function step()\n"
        "    n = n + 1\n"
        "    if n == 4 then\n"
        "      print('failures:', failures)\n"
        "      exit(failures > 0 and 1 or 0)\n"
        "    end\n"
        "  end\n"
        "  get('/json', function(r)\n"
        "    eq(r.status, 201, 'json status')\n"
        "    eq(r.data, '{\"ok\": true}', 'json body')\n"
        "    eq(r.headers['X-Mock'], '1', 'json header')\n"
        "    step()\n"
        "  end)\n"
        "  get('/plain', function(r)\n"
        "    eq(r.status, 200, 'plain status')\n"
        "    eq(r.data, 'hello', 'plain body')\n"
        "    eq(r.headers['Content-Type'], 'text/plain', 'plain type')\n"
        "    step()\n"
        "  end)\n"
        "  get('/empty', function(r)\n"
        "    eq(r.status, 204, 'nil reply status')\n"
        "    step()\n"
        "  end)\n"
        "  get('/nope', function(r)\n"
        "    eq(r.status, 404, '404 status')\n"
        "    eq(r.data, 'missing', '404 body')\n"
        "    step()\n"
        "  end)\n"
        "end\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failures: 0" in result.stdout


def test_tcp_udp_ws_servers_round_trip(tmp_path) -> None:
    # tcp: first package in, reply out; udp: datagram in, reply out;
    # ws: text and binary messages, binary echoes back as a binary frame
    eq = (
        "  local function eq(a, b, msg)\n"
        "    if tostring(a) ~= tostring(b) then\n"
        "      failures = failures + 1\n"
        "      print('FAIL: ' .. msg .. ' ' .. tostring(a) .. '!=' .. tostring(b))\n"
        "    else\n"
        "      print('PASS: ' .. msg)\n"
        "    end\n"
        "  end\n"
    )
    result = run_qa(
        tmp_path,
        "--%%name:roundtrip\n"
        "function QuickApp:onInit()\n"
        "  local failures = 0\n"
        + eq
        + "  local tcp = net.TCPServer()\n"
        "  tcp:listen(0, function(data) return '>' .. data end)\n"
        "  local udp = net.UDPServer()\n"
        "  udp:listen(0, function(data) return 'u:' .. data end)\n"
        "  local ws = net.WebSocketServer()\n"
        "  ws:listen(0, function(message) return message end)\n"
        "  local n = 0\n"
        "  local function step()\n"
        "    n = n + 1\n"
        "    if n == 4 then\n"
        "      print('failures:', failures)\n"
        "      exit(failures > 0 and 1 or 0)\n"
        "    end\n"
        "  end\n"
        "  local function fail(what, e)\n"
        "    failures = failures + 1\n"
        "    print('FAIL: ' .. what .. ' ' .. tostring(e))\n"
        "    step()\n"
        "  end\n"
        "  -- tcp\n"
        "  local c = net.TCPSocket({timeout=5000})\n"
        "  c:connect('127.0.0.1', tcp.port, {\n"
        "    success = function()\n"
        "      c:send('a', {\n"
        "        success = function()\n"
        "          c:read({\n"
        "            success = function(d) eq(d, '>a', 'tcp reply'); c:close(); step() end,\n"
        "            error = function(e) fail('tcp read', e) end,\n"
        "          })\n"
        "        end,\n"
        "        error = function(e) fail('tcp send', e) end,\n"
        "      })\n"
        "    end,\n"
        "    error = function(e) fail('tcp connect', e) end,\n"
        "  })\n"
        "  -- udp\n"
        "  local u = net.UDPSocket({timeout=5000})\n"
        "  u:sendTo('b', '127.0.0.1', udp.port, {\n"
        "    success = function()\n"
        "      u:receive({\n"
        "        success = function(d) eq(d, 'u:b', 'udp reply'); u:close(); step() end,\n"
        "        error = function(e) fail('udp recv', e) end,\n"
        "      })\n"
        "    end,\n"
        "    error = function(e) fail('udp send', e) end,\n"
        "  })\n"
        "  -- ws text\n"
        "  local w = net.WebSocketClient({timeout=5000})\n"
        "  w:addEventListener('connected', function() w:send('hi') end)\n"
        "  w:addEventListener('dataReceived', function(d, bin)\n"
        "    eq(d, 'hi', 'ws text')\n"
        "    eq(bin, false, 'ws text frame')\n"
        "    w:close()\n"
        "    step()\n"
        "  end)\n"
        "  w:addEventListener('error', function(e) fail('ws', e) end)\n"
        "  w:connect('ws://127.0.0.1:' .. ws.port)\n"
        "  -- ws binary (0xAB 0x01 0x02 in latin-1, byte-safe round trip)\n"
        "  local b = net.WebSocketClient({timeout=5000})\n"
        "  b:addEventListener('connected', function()\n"
        "    b:sendBinary(string.char(0xAB, 0x01, 0x02))\n"
        "  end)\n"
        "  b:addEventListener('dataReceived', function(d, bin)\n"
        "    eq(d, string.char(0xAB, 0x01, 0x02), 'ws binary')\n"
        "    eq(bin, true, 'ws binary frame')\n"
        "    b:close()\n"
        "    step()\n"
        "  end)\n"
        "  b:addEventListener('error', function(e) fail('wsbin', e) end)\n"
        "  b:connect('ws://127.0.0.1:' .. ws.port)\n"
        "end\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failures: 0" in result.stdout


def test_tcp_server_persistent_connection_and_binary(tmp_path) -> None:
    # the TCP server keeps ONE connection open across requests (until the
    # client closes), the handler gets a stable conn id, nil = no reply, and
    # binary payloads cross the bridge byte-exact both ways
    result = run_qa(
        tmp_path,
        "--%%name:persist\n"
        "function QuickApp:onInit()\n"
        "  local failures = 0\n"
        "  local function eq(a, b, msg)\n"
        "    if tostring(a) ~= tostring(b) then\n"
        "      failures = failures + 1\n"
        "      print('FAIL: ' .. msg .. ' ' .. tostring(a) .. '!=' .. tostring(b))\n"
        "    else print('PASS: ' .. msg) end\n"
        "  end\n"
        "  local function fail(what, e)\n"
        "    failures = failures + 1\n"
        "    print('FAIL: ' .. what .. ' ' .. tostring(e))\n"
        "    exit(1)\n"
        "  end\n"
        "  local conns, requests = {}, 0\n"
        "  local srv = net.TCPServer()\n"
        "  srv:listen(0, function(data, conn)\n"
        "    requests = requests + 1\n"
        "    conns[#conns + 1] = conn\n"
        "    if data:sub(1, 6) == 'SILENT' then return nil end\n"
        "    return '>' .. data\n"
        "  end)\n"
        "  local c = net.TCPSocket({timeout=5000})\n"
        "  c:connect('127.0.0.1', srv.port, {\n"
        "    success = function()\n"
        "      c:send('a', { success = function()\n"
        "        c:read({ success = function(d)\n"
        "          eq(d, '>a', 'first reply')\n"
        "          c:send('SILENT', { success = function()\n"
        "            c:send('b', { success = function()\n"
        "              c:read({ success = function(d)\n"
        "                eq(d, '>b', 'reply after nil')\n"
        "                local blob = string.char(0, 1, 127, 128, 156, 255)\n"
        "                c:send(blob, { success = function()\n"
        "                  c:read({ success = function(d)\n"
        "                    eq(d, '>' .. blob, 'binary round trip')\n"
        "                    eq(conns[1], conns[2], 'stable conn id')\n"
        "                    eq(conns[1], conns[3], 'stable conn id across requests')\n"
        "                    eq(requests, 4, 'four requests')\n"
        "                    print('failures:', failures)\n"
        "                    exit(failures > 0 and 1 or 0)\n"
        "                  end, error = function(e) fail('read', e) end })\n"
        "                end, error = function(e) fail('send', e) end })\n"
        "              end, error = function(e) fail('read', e) end })\n"
        "            end, error = function(e) fail('send', e) end })\n"
        "          end, error = function(e) fail('send', e) end })\n"
        "        end, error = function(e) fail('read', e) end })\n"
        "      end, error = function(e) fail('send', e) end })\n"
        "    end,\n"
        "    error = function(e) fail('connect', e) end,\n"
        "  })\n"
        "end\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for line in ("first reply", "reply after nil", "binary round trip", "stable conn id"):
        assert f"PASS: {line}" in result.stdout
    assert "failures: 0" in result.stdout


def test_server_port_conflict_raises_lua_error(tmp_path) -> None:
    # a taken port is a synchronous Lua error in the QA
    result = run_qa(
        tmp_path,
        "--%%name:conflict\n"
        "function QuickApp:onInit()\n"
        "  local a = net.HTTPServer()\n"
        "  a:listen(0, function(req) return 'ok' end)\n"
        "  local ok, err = pcall(function()\n"
        "    local b = net.HTTPServer()\n"
        "    b:listen(a.port, function(req) return 'x' end)\n"
        "  end)\n"
        "  print('CAUGHT', ok, tostring(err))\n"
        "  exit(ok and 1 or 0)\n"
        "end\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CAUGHT false" in result.stdout
    assert "net.HTTPServer" in result.stdout  # the error names the kind


def test_server_close_stops_listening(tmp_path) -> None:
    # after :close() a new client connection fails
    result = run_qa(
        tmp_path,
        "--%%name:closed\n"
        "function QuickApp:onInit()\n"
        "  local srv = net.HTTPServer()\n"
        "  srv:listen(0, function(req) return 'ok' end)\n"
        "  local port = srv.port\n"
        "  srv:close()\n"
        "  net.HTTPClient():request('http://127.0.0.1:' .. port .. '/x', {\n"
        "    success = function() print('UNEXPECTED SUCCESS'); exit(1) end,\n"
        "    error = function(err) print('CLOSED ERR'); exit(0) end,\n"
        "  })\n"
        "end\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CLOSED ERR" in result.stdout


def test_handler_error_is_http_500(tmp_path) -> None:
    # a handler that raises replies 500 with the error text
    result = run_qa(
        tmp_path,
        "--%%name:handler_err\n"
        "function QuickApp:onInit()\n"
        "  local srv = net.HTTPServer()\n"
        "  srv:listen(0, function(req) error('boom') end)\n"
        "  net.HTTPClient():request('http://127.0.0.1:' .. srv.port .. '/x', {\n"
        "    success = function(r)\n"
        "      print('GOT', r.status, r.data)\n"
        "      local ok = r.status == 500 and string.find(r.data, 'boom')\n"
        "      exit(ok and 0 or 1)\n"
        "    end,\n"
        "    error = function(err) print('ERR', err); exit(1) end,\n"
        "  })\n"
        "end\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GOT 500" in result.stdout
