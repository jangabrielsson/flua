"""QuickApp model: isolated environments, per-QA timers, config copy."""

import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


async def wait_until(predicate, timeout: float = 3.0) -> None:

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.01)


def qa_timer_count(engine: LuaEngine, qa_id: int) -> int:
    return engine.qa_timer_count(qa_id)


@pytest.mark.asyncio
async def test_qa_environments_are_isolated(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text("x = 'from-a'\nsetTimeout(function() print('A', x) end, 20)\n")
    b = tmp_path / "b.lua"
    b.write_text("x = 'from-b'\nsetTimeout(function() print('B', x) end, 20)\n")
    engine = LuaEngine()
    await engine.start()
    try:
        id_a = engine.start_qa(str(a), None, {}, str(a))
        id_b = engine.start_qa(str(b), None, {}, str(b))
        assert id_a == 5000  # engine-assigned ids start at 5000
        assert id_b == 5001
        await wait_until(lambda: not engine.has_pending_work())
        # Python-side QA directory: ids in start order, resolved names, status
        assert engine.qa_ids() == [id_a, id_b]
        assert engine.qa_info(id_a)["name"] == "a"  # basename without suffix
        assert engine.qa_info(id_a)["loaded"] is True
        assert engine.qa_info(id_b)["name"] == "b"
        assert engine.qa_instance(id_a).name == "a"
        out = capsys.readouterr().out
        assert "A from-a" in out
        assert "B from-b" in out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_qa_timers_are_tracked(tmp_path) -> None:
    a = tmp_path / "a.lua"
    a.write_text("setTimeout(function() end, 400)\nsetTimeout(function() end, 800)\n")
    b = tmp_path / "b.lua"
    b.write_text("setTimeout(function() end, 300)\n")
    engine = LuaEngine()
    await engine.start()
    try:
        id_a = engine.start_qa(str(a), None, {}, str(a))
        id_b = engine.start_qa(str(b), None, {}, str(b))
        # after the 0 ms bootstrap timers fire and the QAs schedule their
        # own timers, QA a tracks two and QA b tracks one
        await wait_until(
            lambda: qa_timer_count(engine, id_a) == 2 and qa_timer_count(engine, id_b) == 1
        )
        await wait_until(lambda: not engine.has_pending_work())
        assert qa_timer_count(engine, id_a) == 0  # fired timers untrack
        assert qa_timer_count(engine, id_b) == 0
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_qa_config_copy(tmp_path, capsys) -> None:
    a = tmp_path / "a.lua"
    a.write_text("print('CFG', _FLUA.config.name, _FLUA.config.speed)\n")
    engine = LuaEngine(speed=2.0, config={"speed": 2.0})
    await engine.start()
    try:
        # the CLI merges global config + the QA's local params into the copy
        engine.start_qa(str(a), None, {"speed": 2.0, "name": "qa-a"}, str(a))
        await wait_until(lambda: not engine.has_pending_work())
        assert "CFG qa-a 2.0" in capsys.readouterr().out
    finally:
        await engine.stop()


def test_cli_runs_multiple_qas_isolated(tmp_path) -> None:
    a = tmp_path / "a.lua"
    a.write_text(
        "--%%name:qa-a\nx = 'a'\nsetTimeout(function() print('A', x, _FLUA.config.name) end, 20)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "--%%name:qa-b\n"
        "--%%instant:true\n"  # global param: copied up, last file wins
        "x = 'b'\n"
        "setTimeout(function() print('B', x, _FLUA.config.name); exit(0) end, 3600000)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(a), str(b)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A a qa-a" in result.stdout
    assert "B b qa-b" in result.stdout


def test_qa_g_aliases_its_own_environment(tmp_path) -> None:
    # the HC3 model: each QA is its own Lua state, _G IS its globals.
    # QA code using _G.xxx sees its own environment — writes stay inside
    # the QA, standard globals resolve through the same table
    a = tmp_path / "a.lua"
    a.write_text(
        "--%%name:g_a\n"
        "_G.marker = 'A'\n"
        "print('A', _G.marker, _G.print == print)\n"
        "exit(0)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "--%%name:g_b\n"
        "print('B', tostring(_G.marker))\n"
        "exit(0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(a), str(b)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A A true" in result.stdout  # _G is the QA's own environment
    assert "B nil" in result.stdout  # writes never leak into another QA


@pytest.mark.asyncio
async def test_bundled_library_dollar_files(tmp_path, capsys) -> None:
    # --%%file:$name.lua loads a library bundled WITH flua
    # (src/flua/lua/lib, shipped in the wheel) — it behaves like any QA
    # file: loads before main, travels in the .fqa export
    script = tmp_path / "bundled.lua"
    script.write_text(
        "--%%name:bundled_test\n"
        "--%%type:com.fibaro.binarySwitch\n"
        "--%%file:$event_mgr.lua,em\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  print('HAS', fibaro.EventMgr ~= nil, fibaro.midnight ~= nil)\n"
        "  exit(0)\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id, err = engine.load_qa_file(str(script))
        assert err is None, err
        await asyncio.sleep(0.3)
        # the bundled file is part of the QA's file set (it ships in .fqa)
        files = engine.qa_file_list(qa_id)
        assert {f["name"] for f in files} == {"main", "em"}
        export = engine.qa_export(qa_id)
        assert "EventMgr" in next(f["content"] for f in export["files"] if f["name"] == "em")
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "HAS true true" in out  # the bundled lib's globals are available


def test_bundled_library_errors(tmp_path) -> None:
    # a missing bundled lib or a path-escape attempt is a loud error
    engine = LuaEngine()
    bad = tmp_path / "bad.lua"
    bad.write_text(
        "--%%name:bad\n--%%file:$nope.lua,x\n-- --------------- EOH ---------------\n"
        "function QuickApp:onInit() end\n"
    )
    _qa_id, err = engine.load_qa_file(str(bad))
    assert err and "bundled library not found" in err
    escape = tmp_path / "esc.lua"
    escape.write_text(
        "--%%name:esc\n--%%file:$../evil.lua,x\n-- --------------- EOH ---------------\n"
        "function QuickApp:onInit() end\n"
    )
    _qa_id2, err2 = engine.load_qa_file(str(escape))
    assert err2 and "bad bundled library name" in err2


def test_include_directive_adds_files_to_a_qa(tmp_path) -> None:
    # a QA includes a defaults file whose --%%file entries append to the
    # QA's own files; both paths resolve relative to the main file
    (tmp_path / "defaults.lua").write_text("--%%file:extra.lua,extra\n")
    (tmp_path / "extra.lua").write_text("print('EXTRA LOADED')\nfibaro.foo = 'FOO'\n")
    (tmp_path / "lib.lua").write_text("print('LIB LOADED')\nfunction helper() return 42 end\n")
    (tmp_path / "main.lua").write_text(
        "--%%name:with_defaults\n"
        "--%%type:com.fibaro.binarySwitch\n"
        "--%%include:defaults.lua\n"
        "--%%file:lib.lua,lib\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  print('MAIN', fibaro.foo, helper())\n"
        "end\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "main.lua"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EXTRA LOADED" in result.stdout  # the included file's file loads first
    assert "LIB LOADED" in result.stdout  # the QA's own file still loads
    assert "MAIN FOO 42" in result.stdout  # both sets are available in main


def test_example_self_test_passes_and_exits_zero() -> None:
    # examples/selfTest.lua is the living fixture for the self-test pattern
    # (assert inside the QA, exit with the failure count): the example must
    # keep passing — it is the canonical sample agents copy from
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/selfTest.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: the device is visible in the sim" in result.stdout
    assert "PASS: updateProperty round trip (50)" in result.stdout
    assert "failures: 0" in result.stdout


def test_examples_qa_pair_calls_each_other() -> None:
    # examples/qa3.lua + qa4.lua: QAs find each other by name and drive each
    # other through fibaro.call (device actions via the pump).
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/qa3.lua", "examples/qa4.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "qa4: turning qa-three on" in result.stdout
    assert "qa3: turned on" in result.stdout
    assert "qa4: got qa3 is on" in result.stdout
    assert "qa4: turning qa-three off" in result.stdout
    assert "qa3: turned off" in result.stdout


def test_example_api_first_qa_gets_5000_and_getvalue(tmp_path) -> None:
    # fibaro.getValue(self.id, "value") — the QA's OWN device, first QA = 5000.
    # Self-contained script (examples/api.lua is a run-forever demo now, and
    # shared example files must not couple the suite to their lifetime).
    script = tmp_path / "api-demo.lua"
    script.write_text(
        "--%%name:api-demo\n"
        "--%%type:com.fibaro.multilevelSwitch\n"
        "function QuickApp:onInit()\n"
        "  print('Value:', fibaro.getValue(self.id, 'value'))\n"
        "end\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[api-demo5000]" in result.stdout
    assert "Value: 0" in result.stdout  # the multilevelSwitch skeleton default


def test_mobdebug_e_bootstrap_does_not_consume_qa_id(tmp_path) -> None:
    # the VS Code mobdebug extension launches interpreters as
    # -l <package> -e "<debugger bootstrap>" <script> — the bootstrap must
    # run as a main-state preamble, NOT as QA 5000, so the script keeps 5000
    script = tmp_path / "api-demo.lua"
    script.write_text(
        "--%%name:api-demo\nfunction QuickApp:onInit() print('BOOT') end\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flua",
            "--api",
            "local",
            "-l",
            "mobdebug",
            "-e",
            'require("mobdebug")',
            str(script),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[api-demo5000]" in result.stdout
    assert "api-demo5001" not in result.stdout


def test_mobdebug_bootstrap_does_not_hide_main_script_mode(tmp_path) -> None:
    # the injected -e bootstrap is the first spec, but the engine mode still
    # follows the MAIN SCRIPT's --%%mode directive (the peek must skip the
    # bootstrap) — without HC3 credentials a missed peek would exit with the
    # HC3_URL error instead of running offline
    script = tmp_path / "main.lua"
    script.write_text("--%%mode:offline\nprint('RAN')\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flua",
            "-l",
            "mobdebug",
            "-e",
            'require("mobdebug")',
            str(script),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mode offline" in result.stdout
    assert "RAN" in result.stdout


@pytest.mark.asyncio
async def test_fibaro_get_returns_value_and_modified(tmp_path, capsys) -> None:
    script = tmp_path / "g.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  local v, m = fibaro.get(self.id, 'value')\n"
        "  print('GET', v, type(m) == 'number')\n"
        "  print('GVAL', fibaro.getValue(self.id, 'value'))\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
        out = capsys.readouterr().out
        assert "GET false true" in out
        assert "GVAL false" in out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_tag_bound_before_qa_code_runs(tmp_path, capsys) -> None:
    # __TAG is <name><id> from the moment the QA's files execute — a QA may
    # have no onInit at all, but its logs still carry the QA tag (not FLUA)
    script = tmp_path / "tagged.lua"
    script.write_text(
        "--%%name:tagged\n"
        "print('TAG', __TAG)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "TAG tagged5000" in out
    # the default fibaro debug tag (print routes through it) is the same
    assert "[tagged5000]" in out


# -- dynamic loading (loadQAfromFile / loadQAfromString) ------------------------


@pytest.mark.asyncio
async def test_dynamic_load_from_file(tmp_path, capsys) -> None:
    target = tmp_path / "loaded.lua"
    target.write_text(
        "--%%name:loaded-qa\n"
        "--%%type:com.fibaro.remoteColorController\n"
        "function QuickApp:turnOn() print('LOADED ON', self.id) end\n"
    )
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        "  local id, err = _FLUA.loadQAfromFile('" + str(target) + "')\n"
        "  print('GOT', id, err)\n"
        "  if id then\n"
        "    fibaro.call(id, 'turnOn') -- same callback: must reach the new QA\n"
        "    local dev = api.get('/devices/'..id)\n"
        "    print('DEV', dev.name, dev.type, dev.roomID)\n"
        "  end\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "GOT 5001" in out
    assert "LOADED ON 5001" in out
    # --%% annotations from the loaded file drive name/type; the type
    # skeleton supplies the default room
    assert "DEV loaded-qa com.fibaro.remoteColorController 219" in out


@pytest.mark.asyncio
async def test_dynamic_load_fqa_from_file(tmp_path, capsys) -> None:
    # _FLUA.loadFQAfromFile: unpack a .fqa package to a temp dir, then the
    # loadQAfromFile pipeline (name/type come from the package header)
    pack = tmp_path / "pack.fqa"
    pack.write_text(
        json.dumps(
            {
                "name": "packed-qa",
                "type": "com.fibaro.binarySwitch",
                "files": [
                    {
                        "name": "main",
                        "isMain": True,
                        "content": "function QuickApp:turnOn() print('PACKED ON', self.id) end\n",
                    }
                ],
            }
        )
    )
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        "  local id, err = _FLUA.loadFQAfromFile('" + str(pack) + "')\n"
        "  print('GOT', id, err)\n"
        "  if id then\n"
        "    fibaro.call(id, 'turnOn')\n"
        "    local dev = api.get('/devices/'..id)\n"
        "    print('DEV', dev.name, dev.type)\n"
        "  end\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "GOT 5001" in out
    assert "PACKED ON 5001" in out
    assert "DEV packed-qa com.fibaro.binarySwitch" in out


@pytest.mark.asyncio
async def test_dynamic_load_fqa_rejects_non_package(tmp_path, capsys) -> None:
    # a non-.fqa file is rejected with the CLI's error, not loaded as a QA
    plain = tmp_path / "plain.lua"
    plain.write_text("print('x')\n")
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        "  local id, err = _FLUA.loadFQAfromFile('" + str(plain) + "')\n"
        "  print('BAD', id, err)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "BAD nil" in out
    assert "cannot open" in out


def test_cli_directive_injection(tmp_path) -> None:
    # -D/--directive injects --%% lines as if appended to every QA's header —
    # testing foreign code without editing it
    script = tmp_path / "app.lua"
    script.write_text(
        "--%%name:original\n"
        "print('OK')\n"
        "setTimeout(function()\n"
        "  local dev = api.get('/devices/'.._FLUA.qaId)\n"
        "  local qv = dev.properties.quickAppVariables[1]\n"
        "  print('X', qv and qv.name, qv and qv.value)\n"
        "  exit(0)\n"
        "end, 10)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "-D", "name:injected", "-D", "var:x=42", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[injected5000]: OK" in result.stdout  # the injected name wins
    assert "[injected5000]: X x 42" in result.stdout  # and the injected var exists
    # an empty -D is rejected up front
    result = subprocess.run(
        [sys.executable, "-m", "flua", "-D", "", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0 and "-D needs a directive" in result.stderr


def test_cli_directory_override_file(tmp_path) -> None:
    # .flua-directives next to the main file overrides the QA's own header
    # (tester wins), and -D wins over the file — the zero-config way to test
    # foreign QAs from VS Code (no QA edits, no launch.json edits)
    script = tmp_path / "app.lua"
    script.write_text(
        "--%%name:original\n"
        "--%%var:host='old'\n"
        "print('OK')\n"
        "setTimeout(function()\n"
        "  local dev = api.get('/devices/'.._FLUA.qaId)\n"
        "  local qv = dev.properties.quickAppVariables[1]\n"
        "  print('X', dev.name, qv and qv.name, qv and qv.value)\n"
        "  exit(0)\n"
        "end, 10)\n"
    )
    (tmp_path / ".flua-directives").write_text(
        "--%%name:overridden\n--%%var:host='new'\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[overridden5000]: OK" in result.stdout  # the file wins over the header
    assert "[overridden5000]: X overridden host new" in result.stdout
    # -D wins over the override file (explicit beats implicit)
    result = subprocess.run(
        [sys.executable, "-m", "flua", "-D", "name:cli", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[cli5000]: OK" in result.stdout
    assert "[cli5000]: X cli host new" in result.stdout  # the var override still applies


def test_cli_override_file_is_directory_scoped(tmp_path) -> None:
    # discovery keys on each main file's own directory: a run with two QAs
    # in two directories applies only the first directory's override file
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "app.lua").write_text(
        "--%%name:a-orig\nprint('OK')\n"
        "setTimeout(function() print('A', _FLUA.config.name); exit(0) end, 10)\n"
    )
    (dir_b / "app.lua").write_text(
        "--%%name:b-orig\nprint('OK')\n"
        "setTimeout(function() print('B', _FLUA.config.name); exit(0) end, 10)\n"
    )
    (dir_a / ".flua-directives").write_text("--%%name:a-over\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(dir_a / "app.lua"), str(dir_b / "app.lua")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A a-over" in result.stdout
    assert "B b-orig" in result.stdout


def test_cli_override_file_next_to_fqa_applies_inside_does_not(tmp_path) -> None:
    # for a .fqa script the override file is discovered next to the package,
    # not inside it — a bundled .flua-directives is the author's file, not
    # the tester's override
    pack = tmp_path / "pack.fqa"
    pack.write_text(
        json.dumps(
            {
                "name": "packed-qa",
                "type": "com.fibaro.binarySwitch",
                "files": [
                    {
                        "name": "main",
                        "isMain": True,
                        "content": "print('OK')\n"
                        "setTimeout(function() print('N', _FLUA.config.name); exit(0) end, 10)\n",
                    },
                    {
                        "name": ".flua-directives",
                        "isMain": False,
                        "content": "--%%name:inside\n",
                    },
                ],
            }
        )
    )
    (tmp_path / ".flua-directives").write_text("--%%name:outside\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(pack)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "N outside" in result.stdout  # the file next to the .fqa applied
    assert "inside" not in result.stdout  # the bundled file never auto-applies


@pytest.mark.asyncio
async def test_load_qa_from_string_directives_spawn_variants(tmp_path, capsys) -> None:
    # the directives array on loadQAfromString lets one code string spawn
    # several QAs under different names
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "local code = [[--%%name:base\nfunction QuickApp:turnOn() print('HI', self.id) end]]\n"
        "setTimeout(function()\n"
        "  local a, ea = _FLUA.loadQAfromString(code, {[[name:alpha]]})\n"
        "  local b, eb = _FLUA.loadQAfromString(code, {[[name:beta]]})\n"
        "  print('IDS', a, ea, b, eb)\n"
        "  if a and b then\n"
        "    fibaro.call(a, 'turnOn')\n"
        "    fibaro.call(b, 'turnOn')\n"
        "    print('NAMES', api.get('/devices/'..a).name, api.get('/devices/'..b).name)\n"
        "  end\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "IDS 5001 nil 5002 nil" in out
    assert "HI 5001" in out and "HI 5002" in out
    assert "NAMES alpha beta" in out


@pytest.mark.asyncio
async def test_device_created_and_removed_events_reach_subscribers(tmp_path, capsys) -> None:
    # a RefreshStateSubscriber sees DeviceCreatedEvent when another QA is
    # loaded and DeviceRemovedEvent when a device is deleted through the API
    target = tmp_path / "loaded.lua"
    target.write_text("--%%name:loaded-qa\nfunction QuickApp:onInit() end\n")
    watcher = tmp_path / "watcher.lua"
    watcher.write_text(
        "local sub = RefreshStateSubscriber()\n"
        "sub:subscribe(function(e)\n"
        "  return e.type == 'DeviceCreatedEvent' or e.type == 'DeviceRemovedEvent'\n"
        "end, function(e)\n"
        "  print('EVENT', e.type, e.data.id)\n"
        "end)\n"
        "sub:run()\n"
        "function QuickApp:onInit()\n"
        "  local id = _FLUA.loadQAfromFile('" + str(target) + "')\n"
        "  print('LOADED', id)\n"
        "  api.delete('/devices/'..id)\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(watcher), None, {}, str(watcher))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "LOADED 5001" in out
    assert "EVENT DeviceCreatedEvent 5001" in out
    assert "EVENT DeviceRemovedEvent 5001" in out


@pytest.mark.asyncio
async def test_debug_messages_record_qa_logs(tmp_path) -> None:
    # QA console lines land in GET /debugMessages with their tag and level
    # (print → debug, fibaro.warning → warning), and DELETE clears them
    script = tmp_path / "dbg.lua"
    script.write_text(
        "--%%name:dbg\n"
        "print('hello')\n"
        "fibaro.warning(__TAG, 'careful')\n"  # HC3 signature: fibaro.warning(tag, msg)
        "exit(0)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
        data, status = engine.api.dispatch("GET", "/debugMessages")
        assert status == 200
        mine = [m for m in data["messages"] if m.get("tag") == "dbg5000"]
        assert [(m["type"], m["message"]) for m in mine] == [
            ("debug", "hello"),
            ("warning", "careful"),
        ]
        assert data["nextLast"] == data["messages"][-1]["id"]
        # the QA's tag shows up in the tags endpoint
        tags, status = engine.api.dispatch("GET", "/debugMessages/tags")
        assert status == 200 and "dbg5000" in tags
        # DELETE clears the buffer
        assert engine.api.dispatch("DELETE", "/debugMessages") == (None, 204)
        data, _ = engine.api.dispatch("GET", "/debugMessages")
        assert data["messages"] == []
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_system_log_records_lifecycle_and_crashes(tmp_path) -> None:
    # /flua/systemLog carries run_start/qa_load/run_stop for a clean run,
    # and crash entries with the QA tag for a failing callback
    script = tmp_path / "boom.lua"
    script.write_text(
        "--%%name:boom\n"
        "setTimeout(function() error('kaboom') end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
        data, status = engine.api.dispatch("GET", "/flua/systemLog")
        assert status == 200
        events = [e["event"] for e in data["entries"]]
        assert "run_start" in events and "run_stop" not in events  # still running
        assert "qa_load" in events
        crashes = [e for e in data["entries"] if e["event"] == "crash"]
        assert crashes and crashes[0]["qa"] == 5000
        assert crashes[0]["tag"] == "boom5000"
        assert "kaboom" in crashes[0]["detail"]
        assert data["nextLast"] == data["entries"][-1]["id"]
    finally:
        await engine.stop()
        data, _ = engine.api.dispatch("GET", "/flua/systemLog")
        assert [e["event"] for e in data["entries"]][-1] == "run_stop"


@pytest.mark.asyncio
async def test_system_log_records_boot_failures(tmp_path) -> None:
    # a QA that cannot load (syntax error) records a qa_error entry
    script = tmp_path / "broken.lua"
    script.write_text("--%%name:broken\nthis is not lua\n")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
        data, _ = engine.api.dispatch("GET", "/flua/systemLog")
        errors = [e for e in data["entries"] if e["event"] == "qa_error"]
        assert errors and errors[0]["qa"] == 5000
        assert errors[0]["tag"] == "broken5000"
        assert "boot failed" in errors[0]["detail"]
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_debug_messages_record_runtime_and_system_lines() -> None:
    # the console buffer is complete in both log modes: flua notices carry
    # the 'flua' tag, runtime-level lines (print from -e/runtime code) land
    # untagged, and QA lines are not double-recorded
    engine = LuaEngine()
    await engine.start()
    try:
        engine.post_log("info", "hello flua")
        engine.execute('print("from runtime")')
        await wait_until(lambda: not engine.has_pending_work())
        data, _ = engine.api.dispatch("GET", "/debugMessages")
        messages = data["messages"]
        system = [(m["type"], m["message"]) for m in messages if m.get("tag") == "flua"]
        assert ("info", "hello flua") in system
        runtime = [(m["type"], m["message"]) for m in messages if m.get("tag") is None]
        assert ("info", "from runtime") in runtime
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_syslog_file_records_system_events(tmp_path) -> None:
    # --syslog FILE: every system event as one JSON line — the complete
    # history, where /flua/systemLog is the bounded in-memory buffer
    syslog_path = tmp_path / "events.jsonl"
    script = tmp_path / "boom.lua"
    script.write_text(
        "--%%name:boom\nsetTimeout(function() error('kaboom') end, 20)\n"
    )
    engine = LuaEngine()
    engine.set_syslog(str(syslog_path))
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    lines = [
        json.loads(line)
        for line in syslog_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events = [entry["event"] for entry in lines]
    assert "run_start" in events and "qa_load" in events and "run_stop" in events
    crash = next(e for e in lines if e["event"] == "crash")
    assert crash["qa"] == 5000 and crash["tag"] == "boom5000"
    assert "kaboom" in crash["detail"]
    assert all("time" in e and "id" in e for e in lines)


@pytest.mark.asyncio
async def test_dynamic_load_from_string(tmp_path, capsys) -> None:
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        "  local id, err = _FLUA.loadQAfromString([[\n"
        "function QuickApp:setValue(v) print('STR QA', v) end\n"
        "]])\n"
        "  print('STRID', id, err)\n"
        "  fibaro.call(id, 'setValue', 42)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        await wait_until(lambda: not engine.has_pending_work())
        assert engine._temp_qa_paths == set()  # temp file consumed and removed
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "STRID 5001" in out
    assert "STR QA 42" in out


@pytest.mark.asyncio
async def test_inline_qa_directives_do_not_leak(tmp_path, capsys) -> None:
    # --%% lines inside an inline QA string must not bleed into the outer
    # QA's config; the EOH comment ends the outer header.
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "--%%name:outer\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function()\n"
        "  print('OUTER', _FLUA.config.name)\n"
        "  local id = _FLUA.loadQAfromString([[\n"
        "--%%name:inner\n"
        "function QuickApp:onInit() print('INNER', _FLUA.config.name) end\n"
        "]])\n"
        "  local dev = api.get('/devices/'..id)\n"
        "  print('INNERDEV', dev.name)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(loader))  # parses the --%% header (EOH-aware)
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "OUTER outer" in out  # not overwritten by the inner --%%name
    assert "INNER inner" in out  # the inner QA parsed its own header
    assert "INNERDEV inner" in out


@pytest.mark.asyncio
async def test_dynamic_load_missing_file(tmp_path, capsys) -> None:
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        "  local id, err = _FLUA.loadQAfromFile('/no/such/file.lua')\n"
        "  print('ERR', id == nil, err ~= nil)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        # wait for the work to complete instead of a fixed sleep: under
        # load the 20ms timer can fire after a 0.3s deadline
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    assert "ERR true true" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_dynamic_load_with_directives(tmp_path, capsys) -> None:
    # _FLUA.loadQAfromFile's second argument: a table of directive strings
    # added to the loaded QA as if appended to its --%% header. var merges
    # per variable (the file's own vars survive), scalars override.
    target = tmp_path / "target.lua"
    target.write_text(
        "--%%var:friend=1\n"
        "--%%var:greeting='from-file'\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  print('TVARS', self:getVariable('friend'), self:getVariable('greeting'))\n"
        "end\n"
    )
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        f"  local id, err = _FLUA.loadQAfromFile([[{target}]], {{[[var:friend=42]]}})\n"
        "  print('LOADED', id ~= nil, err == nil)\n"
        "  local id2, err2 = _FLUA.loadQAfromString([[\n"
        "function QuickApp:onInit() print('SVARS', self:getVariable('greeting')) end\n"
        "  ]], {[[var:greeting='hello']]})\n"
        "  print('LOADED2', id2 ~= nil, err2 == nil)\n"
        f"  local id3, err3 = _FLUA.loadQAfromFile([[{target}]], {{1}})\n"
        "  print('BAD', id3 == nil, err3 ~= nil)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(loader))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    # the dynamic directive overrides friend, the file's own greeting survives
    assert "TVARS 42 from-file" in out
    assert "SVARS hello" in out
    assert "LOADED true true" in out and "LOADED2 true true" in out
    assert "BAD true true" in out  # non-string entries are rejected
    # the dynamically added variable landed in the device, like --%%var
    device = engine.api.state.devices[5001]
    names = {v["name"]: v["value"] for v in device["properties"]["quickAppVariables"]}
    assert names == {"friend": 42, "greeting": "from-file"}


def test_svar_seeds_password_typed_variable(tmp_path) -> None:
    # --%%svar: the device entry carries type='password' (the HC3's web
    # quickvar editor masks it), while getVariable and the API still return
    # the real value. Plain --%%var entries stay untyped.
    script = tmp_path / "secret.lua"
    script.write_text(
        "--%%name:secret\n"
        "--%%svar:user='alice','<set user>'\n"
        "--%%var:user='shadow'\n"
        "--%%var:plain='bob'\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  print('GV', self:getVariable('user'), self:getVariable('plain'))\n"
        "  local dev = api.get('/devices/' .. self.id)\n"
        "  local entries = {}\n"
        "  for _, v in ipairs(dev.properties.quickAppVariables or {}) do entries[v.name] = v end\n"
        "  print('TYPED', entries.user and entries.user.type == 'password',"
        " entries.plain and entries.plain.type == nil)\n"
        "  exit(0)\n"
        "end\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--nogreet", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GV alice bob" in result.stdout
    assert "TYPED true true" in result.stdout


def test_example_dynamic_loading() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/dynamic.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "file load: 5001" in result.stdout
    assert "string load: 5002" in result.stdout
    assert "qa3: turned on" in result.stdout
    assert "string QA: pong" in result.stdout
    assert "inline name: inline-qa" in result.stdout


def test_fibaro_log_lines_are_hc3_styled(tmp_path) -> None:
    script = tmp_path / "log.lua"
    script.write_text(
        'fibaro.debug("TAG", "Test debug")\n'
        'fibaro.trace("TAG", "Test trace")\n'
        'fibaro.warning("TAG", "Test warning")\n'
        'fibaro.error("TAG", "Test error")\n'
        "exit(0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    stamp = r"\[\d{2}\.\d{2}\.\d{4}\]\[\d{2}:\d{2}:\d{2}\]"
    plain_text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert re.search(stamp + r"\[DEBUG  \]\[TAG\]: Test debug", plain_text)
    assert re.search(stamp + r"\[TRACE  \]\[TAG\]: Test trace", plain_text)
    assert re.search(stamp + r"\[WARNING\]\[TAG\]: Test warning", plain_text)
    assert re.search(stamp + r"\[ERROR  \]\[TAG\]: Test error", plain_text)
    # the palette: green DEBUG, cyan TRACE, orange WARNING, red ERROR,
    # gray date/tag — colors are on by default
    assert "\x1b[32m" in result.stdout
    assert "\x1b[36m" in result.stdout
    assert "\x1b[33m" in result.stdout
    assert "\x1b[31;1m" in result.stdout
    assert "\x1b[37m" in result.stdout

    # --color never produces plain output
    plain = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "--color", "never", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert plain.returncode == 0
    assert "\x1b[" not in plain.stdout


def test_print_binary_string_does_not_crash(tmp_path) -> None:
    # utf8.charpattern is a binary pattern (raw bytes, not valid UTF-8).
    # Printing it must not take the process down: the message bridge
    # hex-escapes invalid UTF-8 instead of raising during lupa's strict
    # decode (regression: UnicodeDecodeError -> exit code 1).
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "-e", "print(utf8.charpattern)"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plain_text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert r"[\x00-\x7F\xC2-\xFD][\x80-\xBF]*" in plain_text
    assert "stack traceback" not in plain_text


def test_startup_greeting(tmp_path) -> None:
    script = tmp_path / "greet.lua"
    script.write_text("exit(0)\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(
        r"flua \d+\.\d+\.\d+ \(Lua 5\.\d+, Python 3\.\d+\.\d+\), mode offline",
        result.stdout,
    )

    # --nogreet suppresses the greeting
    quiet = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "--nogreet", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert quiet.returncode == 0
    assert "flua 0.1.0, Lua" not in quiet.stdout


def test_example_qa_pair_runs_together() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flua",
            "--api",
            "local",
            str(REPO_ROOT / "examples" / "qa1.lua"),
            str(REPO_ROOT / "examples" / "qa2.lua"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "qa-one: 1" in result.stdout
    assert "qa-two: 100" in result.stdout
    assert "qa-one: 2" in result.stdout
    assert "qa-two: 200" in result.stdout


def test_exit_terminates_only_the_calling_qa(tmp_path) -> None:
    # HC3 semantics: exit() terminates the QA that called it (each QA is its
    # own process on the HC3; flua runs them cooperatively). Its timers are
    # cancelled; the other QAs keep running.
    a = tmp_path / "a.lua"
    a.write_text(
        "print('A_START')\n"
        "setTimeout(function() print('A_LATE') end, 100)\n"  # cancelled on exit
        "setTimeout(function() print('A_EXIT'); exit(0) end, 10)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text("setTimeout(function() print('B_DONE'); exit(0) end, 200)\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(a), str(b)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A_START" in result.stdout
    assert "A_EXIT" in result.stdout
    assert "A_LATE" not in result.stdout  # the QA's timers died with it
    assert "B_DONE" in result.stdout  # the other QA kept running


def test_exit_inside_interval_kills_the_interval(tmp_path) -> None:
    # regression: exit() from inside a setInterval callback used to be
    # followed by the interval's re-arm, which survived cancel_qa (the
    # re-arm is still a message, not a scheduled timer) and kept the QA
    # ticking forever — the process never drained
    script = tmp_path / "iv.lua"
    script.write_text(
        "local n = 0\n"
        "setInterval(function()\n"
        "  n = n + 1\n"
        "  print('tick', n)\n"
        "  if n >= 3 then exit(0) end\n"
        "end, 20)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tick 3" in result.stdout
    assert "tick 4" not in result.stdout  # the interval died with the QA


def test_os_exit_terminates_the_calling_qa(tmp_path) -> None:
    # os.exit() is the name real HC3 QAs use; flua's QA env shadows os so it
    # terminates the calling QA only — and its timers with it (the interval
    # re-arm after exit is refused, like exit())
    a = tmp_path / "a.lua"
    a.write_text(
        "local n = 0\n"
        "setInterval(function()\n"
        "  n = n + 1\n"
        "  print('A_TICK', n)\n"
        "  if n >= 2 then os.exit(0) end\n"
        "end, 10)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text("setTimeout(function() print('B_DONE'); exit(0) end, 50)\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(a), str(b)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A_TICK 2" in result.stdout
    assert "A_TICK 3" not in result.stdout  # the interval died with the QA
    assert "B_DONE" in result.stdout  # the other QA kept running
    # os still works like os inside a QA (the shadow table falls back to the
    # shared virtual-clock os)
    c = tmp_path / "c.lua"
    c.write_text("print('C_TIME', os.time() > 0)\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(c)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "C_TIME true" in result.stdout


@pytest.mark.asyncio
async def test_type_reports_userdata_for_qa_objects(tmp_path, capsys) -> None:
    # the HC3's QuickApp objects are C userdata; flua's class() tables are
    # marked __USERDATA and the patched type() reports 'userdata' for them
    script = tmp_path / "t.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  print('SELF', type(self))\n"
        "  print('CLASS', type(QuickApp))\n"
        "  print('PLAIN', type({}))\n"
        "  print('NUM', type(42))\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.3)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "SELF userdata" in out
    assert "CLASS userdata" in out
    assert "PLAIN table" in out
    assert "NUM number" in out


@pytest.mark.asyncio
async def test_exited_qa_restart_runs_timers_again(tmp_path, capsys) -> None:
    # after exit(), a restart revives the QA: the new code's timers must not
    # be refused as re-arms of a dead QA
    script = tmp_path / "r.lua"
    script.write_text(
        "local n = 0\n"
        "setInterval(function()\n"
        "  n = n + 1\n"
        "  print('tick', n)\n"
        "  if n >= 2 then exit(0) end\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
        engine.restart_qa(5000)
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert out.count("tick 1") == 2  # once per run: the restart really re-ran
    assert out.count("tick 2") == 2


def test_exit_code_from_failing_qa_becomes_engine_exit_code(tmp_path) -> None:
    # a QA exiting nonzero marks the run failed (last failing QA wins)
    script = tmp_path / "failing.lua"
    script.write_text("setTimeout(function() exit(7) end, 10)\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 7, result.stdout + result.stderr


def test_flua_table_is_per_qa(tmp_path) -> None:
    # each QA has its own _FLUA: qaId/config/arg are stable per QA even in
    # deferred reads, while the API itself is the shared engine table
    a = tmp_path / "a.lua"
    a.write_text(
        "--%%name:qa-a\n"
        "setTimeout(function()\n"
        "  print('A', _FLUA.qaId, _FLUA.config.name)\n"
        "  exit(0)\n"
        "end, 30)\n"
    )
    b = tmp_path / "b.lua"
    b.write_text(
        "--%%name:qa-b\n"
        "setTimeout(function()\n"
        "  print('B', _FLUA.qaId, _FLUA.config.name)\n"
        "  exit(0)\n"
        "end, 30)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(a), str(b)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A 5000 qa-a" in result.stdout
    assert "B 5001 qa-b" in result.stdout


def test_run_for_expiry_exits_nonzero(tmp_path) -> None:
    # a QA that never drains: --run-for's wall deadline cuts the run short
    # — that is a failure, not a green pass (the CI false-pass guard)
    hang = tmp_path / "hang.lua"
    hang.write_text(
        "--%%name:Hang\n"
        "function QuickApp:onInit() print('started, never exits') end\n"
        "setTimeout(function() print('later') end, 60000)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--run-for", "1", str(hang)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "wall cap reached with work pending" in result.stderr
    assert "started, never exits" in result.stdout  # the QA did run


def test_run_for_drained_qa_exits_zero(tmp_path) -> None:
    # the other side of the coin: a QA that finishes before the deadline
    # must still exit 0 (expiry only counts when work was cut short)
    quick = tmp_path / "quick.lua"
    quick.write_text("--%%name:Quick\nfunction QuickApp:onInit() print('done') end\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--run-for", "5", str(quick)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "done" in result.stdout


def test_step_mode_is_deadline_ordered_and_clock_coherent(tmp_path) -> None:
    # --step (plua speedTime semantics): timers fire one deadline at a time
    # and os.time() equals each fired deadline inside the callback — the
    # ER-style re-scheduling loop (delay computed from os.time()) lands on
    # exact absolute times, which --instant corrupts
    script = tmp_path / "step.lua"
    script.write_text(
        "--%%name:Step\n"
        "setTimeout(function() print('A', os.date('%H:%M:%S')) end, 3000)\n"
        "setTimeout(function() exit(0) end, 8000)\n"
        "local function loop()\n"
        "    print('tick', os.date('%H:%M:%S'))\n"
        "    setTimeout(loop, 5000)\n"
        "end\n"
        "setTimeout(loop, 2000)\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flua",
            "--step",
            "--nogreet",
            "--start",
            "2027/01/01 12:00:00",
            str(script),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tick 12:00:02" in result.stdout
    assert "A 12:00:03" in result.stdout
    assert "tick 12:00:07" in result.stdout  # 02 + 5s — the clock stayed coherent
    assert "tick 12:00:12" not in result.stdout  # exit at :08 cut the run


def test_step_conflicts_with_instant_and_speed(tmp_path) -> None:
    script = tmp_path / "qa.lua"
    script.write_text("--%%name:QA\nfunction QuickApp:onInit() print('hi') end\n")
    for extra in (["--instant"], ["--speed", "60"]):
        result = subprocess.run(
            [sys.executable, "-m", "flua", "--step", *extra, str(script)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "mutually exclusive" in result.stderr or "cannot be combined" in result.stderr


def test_step_negative_run_for_fires_far_timers_and_exits_when_idle(tmp_path) -> None:
    # --step + --run-for -N: the negative form is a fixed-duration cap that
    # must not block the deadline jumps step mode exists for — the far
    # timer fires, and the run ends when idle instead of sitting out the
    # wall cap (the ER7 report: 30 s wall with no fire / 11 h hang)
    script = tmp_path / "step.lua"
    script.write_text(
        "--%%name:Step\n"
        "setTimeout(function() print('future fired') end, 9 * 3600 * 1000)\n"
        "print('booted')\n"
    )
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--step", "--run-for", "-30", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    wall = time.monotonic() - started
    assert result.returncode == 0, result.stdout + result.stderr
    assert "future fired" in result.stdout  # the 9h deadline jumped and fired
    assert "booted" in result.stdout
    assert wall < 10, f"run should end when idle, took {wall:.1f}s wall"


def test_step_negative_run_for_wall_cap_is_a_failure(tmp_path) -> None:
    # --step --run-for -N: an endless timer chain steps for at most N WALL
    # seconds — and when the cap cuts it short with work pending, that is
    # exit 1 (the CI false-pass guard), not a silent green
    script = tmp_path / "loop.lua"
    script.write_text(
        "--%%name:Loop\n"
        "local function loop()\n"
        "    setTimeout(loop, 1000)\n"
        "end\n"
        "setTimeout(loop, 1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--step", "--run-for", "-1", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "wall cap reached with work pending" in result.stderr


def test_background_timers_fire_but_never_keep_the_run_alive(tmp_path) -> None:
    # _FLUA.background(fn): the tagged callback still fires while the run
    # lives, but once the real work drains the run exits 0 — even though
    # the housekeeping loop is still scheduled (EventRunner's midnight
    # scheduler under --step --run-for -N)
    script = tmp_path / "bg.lua"
    script.write_text(
        "--%%name:Bg\n"
        "local function loop()\n"
        "    print('bg tick')\n"
        "    setTimeout(loop, 5000)\n"
        "end\n"
        "setTimeout(_FLUA.background(loop), 500)  -- tagged once; reschedules inherit\n"
        "setTimeout(function() print('work done') end, 1000)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--step", "--run-for", "-5", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bg tick" in result.stdout  # the housekeeping timer fired while alive
    assert "work done" in result.stdout


def test_background_only_qa_exits_immediately(tmp_path) -> None:
    # the tag's contract: a QA whose ONLY work is background drains at boot
    # (no --run-for) — a tagged timer never keeps a run alive
    script = tmp_path / "bg.lua"
    script.write_text(
        "--%%name:Bg\n"
        "setTimeout(_FLUA.background(function() print('never fired') end), 60000)\n"
        "print('booted')\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "booted" in result.stdout
    assert "never fired" not in result.stdout


def test_step_rearming_engine_deterministically_rides_the_wall_cap(tmp_path) -> None:
    # the ER report: a daily rule that re-arms itself forever used to exit 0
    # at a RANDOM point (the idle check sampled the re-arm gap — 73–342
    # next-day re-fires). The settle streak makes the decision
    # deterministic: a re-arming engine rides the wall cap and exits 1
    script = tmp_path / "daily.lua"
    script.write_text(
        "--%%name:Daily\n"
        "local function daily()\n"
        "    local t = os.date('*t', os.time())\n"
        "    local next = os.time({year=t.year, month=t.month, day=t.day,"
        " hour=8, min=0, sec=0}) + 86400\n"
        "    setTimeout(daily, (next - os.time()) * 1000)\n"
        "end\n"
        "local t0 = os.date('*t', os.time())\n"
        "local first = os.time({year=t0.year, month=t0.month, day=t0.day,"
        " hour=8, min=0, sec=0})\n"
        "if first <= os.time() then first = first + 86400 end\n"
        "setTimeout(daily, (first - os.time()) * 1000)\n"
    )
    codes = set()
    for _ in range(4):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "flua",
                "--step",
                "--run-for",
                "-1",
                "--start",
                "2027/01/01 07:59:58",
                str(script),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        codes.add(result.returncode)
    assert codes == {1}, f"expected deterministic exit 1, got {codes}"


def test_export_writes_raw_utf8_for_emoji(tmp_path) -> None:
    # the HC3's web importer does not decode \uXXXX surrogate pairs: .fqa
    # files must carry raw UTF-8 (ensure_ascii=False) or emojis outside the
    # BMP (🕒) get mangled on upload
    script = tmp_path / "emoji.lua"
    script.write_text('--%%name:Emoji\n--%%u:{label="L1",text="🕒 clock"}\nprint("🕒")\n')
    out = tmp_path / "emoji.fqa"
    result = subprocess.run(
        [sys.executable, "-m", "flua", "export", str(script), "-o", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = out.read_text(encoding="utf-8")
    assert "🕒" in payload
    assert "\\ud83d" not in payload and "\\uD83D" not in payload


@pytest.mark.slow
def test_watch_survives_boot_errors_and_recovers(tmp_path) -> None:
    # --watch must not terminate on a QA boot error: the error is logged,
    # the process stays alive, and the next save with fixed code restarts
    # the QA (the editor workflow: break it, see the error, fix it)
    script = tmp_path / "qa.lua"
    script.write_text("--%%name:QA\nthis is not lua(\n")
    log = tmp_path / "out.log"
    with open(log, "w") as handle:
        proc = subprocess.Popen(
            [sys.executable, "-m", "flua", "--watch", "--nogreet", str(script)],
            cwd=REPO_ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
    try:
        deadline = time.monotonic() + 10.0
        while "Error loading" not in log.read_text():
            assert proc.poll() is None, "flua exited on a boot error in watch mode"
            assert time.monotonic() < deadline, "the boot error line never appeared"
            time.sleep(0.2)
        # fix the file: the next save must restart the QA — flua stays up
        script.write_text("--%%name:QA\nprint('FIXED')\n")
        deadline = time.monotonic() + 10.0
        while "FIXED" not in log.read_text():
            assert proc.poll() is None, "flua exited before the fixed save restarted"
            assert time.monotonic() < deadline, "the fixed code never ran"
            time.sleep(0.2)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_engine_forces_c_locale_for_lua_patterns() -> None:
    # plua 1.2.79's fix, adopted: Lua's pattern classes (%s/%a/%d) are
    # libc ctype lookups — on Polish/UTF-8 locales isspace(0x85) is true,
    # and 0x85 is the second byte of UTF-8 'ą' (U+0105), so %S+ splits
    # multibyte characters mid-byte. The engine forces LC_CTYPE=C before
    # the Lua runtime exists, on every platform.
    import locale as _locale

    try:
        _locale.setlocale(_locale.LC_CTYPE, "en_US.UTF-8")
    except _locale.Error:
        pytest.skip("no en_US.UTF-8 locale available")
    engine = LuaEngine()
    assert _locale.setlocale(_locale.LC_CTYPE, None) in ("C", "C.UTF-8")  # forced
    # embedders keep UTF-8 text handling: a plain "C" locale on Python
    # <= 3.14 flips locale.getencoding() to ASCII and breaks
    # subprocess(text=True) decode — hence C.UTF-8 where available
    assert _locale.getencoding().lower() in ("utf-8", "utf8")
    lua = engine._lua
    # the reported symptom (pl_PL/Windows): 0x85 is the second byte of
    # UTF-8 'ą' — %s must not eat it, %S+ must not split mid-byte.
    # (macOS's C.UTF-8 still classifies high bytes as %a — a documented
    # platform limit, not asserted here.)
    assert lua.eval("('ą'):match('%s')") is None  # neither byte is a space
    assert lua.eval("('ą'):match('%S+') == 'ą'") is True  # no mid-byte split
