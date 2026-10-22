"""The Modbus mock server example and the HC3 compat it builds on.

Covers three contracts:

- ``string.starts``/``string.ends`` exist (real-HC3 extensions the
  SolarEdge Live QA uses).
- ``--%%var`` directives are visible as ``quickAppVariables`` through the
  sim API *during* ``onInit`` (the HC3 creates the device with
  initialProperties before onInit — QAs that build child devices from
  variable names depend on it).
- ``examples/Modbus Server`` serves the SolarEdge Live QA's wire pattern
  (PDU address = register - 40001, SunSpec base 40000) and its buttons
  change what the client QA reads on its next poll.
"""

import re
import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = REPO_ROOT / "examples" / "Modbus Server"

FLUA = [sys.executable, "-m", "flua", "--api", "local"]


def run_flua(*args: str, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*FLUA, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_string_starts_and_ends() -> None:
    # HC3 string extensions; print separates with tabs
    result = run_flua(
        "-e",
        "print('R', string.starts('com.fibaro.electricMeter', 'com.fibaro.'), "
        "string.ends('file.lua', '.lua'), string.ends('file.lua', ''), "
        "string.starts('abc', 'abx'))",
        "--run-for",
        "1",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"R\s+true\s+true\s+true\s+false", result.stdout)


def test_modbus_server_write_functions_round_trip(tmp_path) -> None:
    # FC6 (write single) and FC16 (write multiple) mutate the map and read
    # back through FC3 — pins the PDU byte offsets of the write handlers
    lib = tmp_path / "modbus_server.lua"
    lib.write_text((EXAMPLE_DIR / "modbus_server.lua").read_text(encoding="utf-8"))
    script = tmp_path / "roundtrip.lua"
    script.write_text(
        "--%%name:RoundTrip\n"
        "local server = require('modbus_server')\n"
        "local word = function(x) return string.char(math.floor(x / 256) % 256, x % 256) end\n"
        "local failures = 0\n"
        "local function check(cond, label)\n"
        "  if cond then print('PASS: ' .. label) else\n"
        "    failures = failures + 1; print('FAIL: ' .. label)\n"
        "  end\n"
        "end\n"
        "function QuickApp:onInit()\n"
        "  local mock = server.serve({}, { port = 0, base = 40001 })\n"
        "  local s = net.TCPSocket({timeout = 5000})\n"
        "  -- one request in flight at a time (the user QA's pattern): send,\n"
        "  -- then read until the expected reply length has arrived\n"
        "  local function exchange(frame, expect, onGot)\n"
        "    s:send(frame, {\n"
        "      success = function()\n"
        "        local buf = ''\n"
        "        local function more()\n"
        "          s:read({\n"
        "            success = function(data)\n"
        "              buf = buf .. data\n"
        "              if #buf >= expect then\n"
        "                onGot(buf:sub(1, expect), buf:sub(expect + 1))\n"
        "              else\n"
        "                more()\n"
        "              end\n"
        "            end,\n"
        "            error = function() check(false, 'read failed'); exit(1) end,\n"
        "          })\n"
        "        end\n"
        "        more()\n"
        "      end,\n"
        "      error = function(e) check(false, 'send failed ' .. tostring(e)); exit(1) end,\n"
        "    })\n"
        "  end\n"
        "  local function fc3Read(addr, count, onRegs)\n"
        "    exchange(string.char(0,0, 0,0, 0,6, 1, 3) .. word(addr) .. word(count),\n"
        "             9 + math.min(count, 125) * 2, function(frame)\n"
        "      local regs = {}\n"
        "      -- parse what the server actually answered (the byte count in the\n"
        "      -- reply caps the read at the Modbus wire maximum of 125)\n"
        "      local n = frame:byte(9) / 2\n"
        "      for i = 1, n do\n"
        "        regs[i] = frame:byte(10 + (i - 1) * 2) * 256 + frame:byte(11 + (i - 1) * 2)\n"
        "      end\n"
        "      onRegs(regs, n)\n"
        "    end)\n"
        "  end\n"
        "  s:connect('127.0.0.1', mock.srv.port, {\n"
        "    success = function()\n"
        "      -- FC6: write 7777 to register 40010 (PDU 9)\n"
        "      exchange(\n"
        "        string.char(0,0, 0,0, 0,6, 1, 6) .. word(9) .. word(7777), 12, function(frame)\n"
        "        check(frame:byte(7) == 1 and frame:byte(8) == 6, 'FC6 reply frame')\n"
        "        -- FC16: write 111, 222 to registers 40020-40021 (PDU 19)\n"
        "        exchange(string.char(0,0, 0,0, 0,11, 1, 16) .. word(19) .. word(2)\n"
        "                 .. string.char(4) .. word(111) .. word(222), 12, function(frame2)\n"
        "          check(frame2:byte(7) == 1 and frame2:byte(8) == 16, 'FC16 reply frame')\n"
        "          -- FC3: read 40010..40021 back and verify the written values\n"
        "          fc3Read(9, 12, function(regs)\n"
        "            check(regs[1] == 7777, 'FC6 value read back (' .. tostring(regs[1]) .. ')')\n"
        "            check(regs[11] == 111 and regs[12] == 222,\n"
        "              'FC16 values read back (' .. tostring(regs[11])\n"
        "              .. ',' .. tostring(regs[12]) .. ')')\n"
        "            -- an oversized read must come back capped at the wire\n"
        "            -- maximum (125 registers, byte count 250) — no overflow\n"
        "            fc3Read(9, 200, function(regs2, n)\n"
        "              check(n == 125,\n"
        "                'oversized read capped at 125 (' .. (\"%d\"):format(n) .. ')')\n"
        "              check(regs2[1] == 7777, 'capped read starts at the requested address')\n"
        "              print('failures: ' .. failures)\n"
        "              exit(failures)\n"
        "            end)\n"
        "          end)\n"
        "        end)\n"
        "      end)\n"
        "    end,\n"
        "    error = function(e) check(false, 'connect ' .. tostring(e)); exit(1) end })\n"
        "end\n",
    )
    result = run_flua(str(script), "--run-for", "20", "--speed", "60")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: FC6 value read back (7777)" in result.stdout
    assert "PASS: FC16 values read back (111,222)" in result.stdout
    assert "PASS: oversized read capped at 125 (125)" in result.stdout
    assert "PASS: capped read starts at the requested address" in result.stdout
    assert "failures: 0" in result.stdout


def test_var_directives_seed_quick_app_variables(tmp_path) -> None:
    # on the HC3 the device exists with initialProperties before onInit;
    # flua must serve --%%var values through the sim API at boot time
    script = tmp_path / "varseed.lua"
    script.write_text(
        "--%%name:VarSeed\n"
        "--%%var:child='42'\n"
        "function QuickApp:onInit()\n"
        "  local dev = api.get('/devices/' .. self.id)\n"
        "  local qav = dev.properties.quickAppVariables or {}\n"
        "  local found = false\n"
        "  for _, v in ipairs(qav) do\n"
        "    if v.name == 'child' and v.value == '42' then found = true end\n"
        "  end\n"
        "  print(found and 'PASS: vars visible at onInit' or 'FAIL: vars missing at onInit')\n"
        "  exit(found and 0 or 1)\n"
        "end\n",
    )
    result = run_flua(str(script), "--run-for", "5")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: vars visible at onInit" in result.stdout


def test_solaredge_mock_serves_client_and_buttons(tmp_path) -> None:
    # A stand-in for the SolarEdge Live QA (same wire pattern: persistent
    # connection, holding register 40084 sent as PDU 40084-40001=83) polls
    # the example mock; the example driver presses the mock's buttons and
    # verifies the client's value follows. The client stops after 8 polls
    # so the run ends when the driver is done. The mock's port is a QA
    # variable: the test binds a free port first so a parallel dev session
    # (e.g. a VS Code debug run holding 1502) never breaks it.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = tmp_path / "client.lua"
    client.write_text(
        "--%%name:SolarEdge Live\n"
        "--%%type:com.fibaro.powerMeter\n"
        "-- Mini stand-in for the user QA's Modbus pattern (no children,\n"
        "-- mainRegister 40084 + scale factor).\n"
        "local socket = net.TCPSocket({timeout = 5000})\n"
        "local polls = 0\n"
        "local connected = false\n"
        "local function retrySoon()\n"
        "  socket:close()\n"
        "  connected = false\n"
        "  setTimeout(function() QuickApp:readOnce() end, 2000)  -- the mock may still be booting\n"
        "end\n"
        "function QuickApp:readOnce()\n"
        "  polls = polls + 1\n"
        "  if polls > 8 then return end  -- done: let the run end\n"
        "  local tx = string.char(0,0, 0,0, 0,6, 1, 3) .. string.char(0, 83) .. string.char(0, 2)\n"
        "  local function send()\n"
        "    socket:write(tx, {\n"
        "      success = function()\n"
        "        socket:read({\n"
        "          success = function(response)\n"
        "            if response and #response >= 13 then\n"
        "              local v = response:byte(10) * 256 + response:byte(11)\n"
        "              self:updateProperty('value', v)\n"
        "            end\n"
        "            setTimeout(function() self:readOnce() end, 5000)\n"
        "          end,\n"
        "          error = retrySoon,\n"
        "        })\n"
        "      end,\n"
        "      error = retrySoon,\n"
        "    })\n"
        "  end\n"
        "  if connected then\n"
        "    send()\n"
        "  else\n"
        "    socket:connect('127.0.0.1', " + str(port) + ", {\n"
        "      success = function() connected = true; send() end,\n"
        "      error = retrySoon,\n"
        "    })\n"
        "  end\n"
        "end\n"
        "function QuickApp:onInit() self:readOnce() end\n",
    )
    result = run_flua(
        str(client),
        str(EXAMPLE_DIR / "solaredge_mock.lua"),
        str(EXAMPLE_DIR / "run_solaredge.lua"),
        "-D",
        f"var:port={port}",
        "--run-for",
        "45",
        "--speed",
        "60",
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for line in (
        "PASS: initial value arrives on the first poll",
        "PASS: AC power follows 'Sun +500W'",
        "PASS: AC power follows 'Sun -500W'",
    ):
        assert line in result.stdout
    assert "failures: 0" in result.stdout
