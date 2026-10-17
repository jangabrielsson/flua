"""Agent-facing DX: flua-test, --log json/--logfile, UI helpers, --tool ui.

The verify-loop contract (docs/notes-agents.md): self-asserting QAs, exit
codes as the verdict, machine-readable logs, UI assertions from Lua, and a
text rendering of the UI for eyeball checks.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FLOA = [sys.executable, "-m", "flua"]


def _run(
    *args: str, cwd: Path, timeout: int = 60, nogreet: bool = True
) -> subprocess.CompletedProcess:
    prefix = ["--nogreet"] if nogreet else []
    return subprocess.run(
        [*FLOA, *prefix, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def test_flua_test_library_counts_and_exits(tmp_path) -> None:
    (tmp_path / "qa.lua").write_text(
        "--%%name:testlib\n"
        "local Test = require('flua-test')\n"
        "local t = Test.new()\n"
        "t:expect(1 == 1, 'one is one')\n"
        "t:expect(1 == 2, 'one is two')\n"
        "t:assert_eq({a=1}, {a=1}, 'deep equal')\n"
        "t:assert_json('{\"x\": 1}', 'json parses')\n"
        "t:assert_json('{bad', 'json fails')\n"
        "t:finish()\n"
    )
    result = _run("qa.lua", cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PASS: one is one" in result.stdout
    assert "FAIL: one is two" in result.stdout
    assert "PASS: deep equal" in result.stdout
    assert "PASS: json parses" in result.stdout
    assert "FAIL: json fails" in result.stdout
    assert "failures: 2" in result.stdout


def test_flua_test_passing_qa_exits_zero(tmp_path) -> None:
    (tmp_path / "qa.lua").write_text(
        "--%%name:green\n"
        "local Test = require('flua-test')\n"
        "local t = Test.new()\n"
        "setTimeout(function()\n"
        "  t:expect(true, 'all good')\n"
        "  t:finish()\n"
        "end, 20)\n"
    )
    result = _run("qa.lua", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failures: 0" in result.stdout


def test_flua_test_is_per_qa(tmp_path) -> None:
    # each QA loads its own module copy: tags and counters stay separate
    (tmp_path / "a.lua").write_text(
        "--%%name:aaa\n"
        "local Test = require('flua-test')\n"
        "local t = Test.new()\n"
        "setTimeout(function() t:expect(true, 'a passes') t:finish() end, 20)\n"
    )
    (tmp_path / "b.lua").write_text(
        "--%%name:bbb\n"
        "local Test = require('flua-test')\n"
        "local t = Test.new()\n"
        "setTimeout(function() t:expect(false, 'b fails') t:finish() end, 20)\n"
    )
    result = _run("a.lua", "b.lua", cwd=tmp_path)
    assert result.returncode == 1
    assert "PASS: a passes" in result.stdout
    assert "FAIL: b fails" in result.stdout
    assert "failures: 0" in result.stdout  # a's own counter, not shared
    assert "failures: 1" in result.stdout  # b's own counter


def test_log_json_emits_json_lines_and_exit_code(tmp_path) -> None:
    (tmp_path / "qa.lua").write_text(
        "--%%name:jsonlog\n"
        "local Test = require('flua-test')\n"
        "local t = Test.new()\n"
        "print('plain line')\n"
        "t:expect(false, 'nope')\n"
        "t:finish()\n"
    )
    result = _run("--log", "json", "qa.lua", cwd=tmp_path)
    assert result.returncode == 1
    entries = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert entries, "stdout must be pure JSON lines"
    assert all("time" in e and "level" in e and "msg" in e for e in entries)
    assert entries[0]["msg"] == "plain line"
    assert entries[0]["qaid"] == 5000
    assert entries[0]["tag"] == "jsonlog5000"
    assert any(e["msg"] == "FAIL: nope" for e in entries)
    # stderr carries the verdict, stdout stays pure
    assert "exited with code 1" in result.stderr


def test_logfile_copies_text_log_without_ansi(tmp_path) -> None:
    (tmp_path / "qa.lua").write_text(
        "--%%name:filelog\nsetTimeout(function() print('logged line') exit(0) end, 20)\n"
    )
    result = _run("--logfile", "run.log", "qa.lua", cwd=tmp_path)
    assert result.returncode == 0
    log = (tmp_path / "run.log").read_text(encoding="utf-8")
    assert "logged line" in log
    assert "\x1b[" not in log


def test_logfile_with_json_log(tmp_path) -> None:
    (tmp_path / "qa.lua").write_text(
        "--%%name:filelog\nsetTimeout(function() print('logged line') exit(0) end, 20)\n"
    )
    result = _run("--log", "json", "--logfile", "run.json", "qa.lua", cwd=tmp_path)
    assert result.returncode == 0
    lines = [line for line in (tmp_path / "run.json").read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["msg"] == "logged line"


def test_ui_event_and_getview_helpers(tmp_path) -> None:
    (tmp_path / "qa.lua").write_text(
        "--%%name:uihelp\n"
        '--%%u:{button="B1",text="Press me",onReleased="fopp"}\n'
        "-- --------------- EOH ---------------\n"
        "local Test = require('flua-test')\n"
        "local t = Test.new()\n"
        "function QuickApp:onInit()\n"
        "  self:updateView('B1', 'text', 'New label')\n"
        "  setTimeout(function()\n"
        "    local d, s = _FLUA.uiEvent('B1', 'onReleased')\n"
        "    t:expect(s == 200, 'uiEvent returns 200')\n"
        "    local view = self:getView()\n"
        "    local comps = view['$jason'].body.sections.items[1].components\n"
        "    t:expect(comps[1].text == 'New label', 'getView reflects updateView')\n"
        "  end, 100)\n"
        "end\n"
        "function QuickApp:fopp()\n"
        "  t:expect(true, 'button callback fired')\n"
        "  t:finish()\n"
        "end\n"
    )
    result = _run("qa.lua", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: uiEvent returns 200" in result.stdout
    assert "PASS: getView reflects updateView" in result.stdout
    assert "PASS: button callback fired" in result.stdout


def test_flua_test_shipped_file_works_like_require(tmp_path) -> None:
    # --%%file:$flua-test.lua ships the same library as a QA file: require
    # still works (the file registers itself in package.preload) and the
    # global spelling (fluaTest.new()) works too — all asserts active in flua
    (tmp_path / "qa.lua").write_text(
        "--%%name:shipped\n"
        "--%%file:$flua-test.lua,flua_test\n"
        "-- --------------- EOH ---------------\n"
        "local Test = require('flua-test')\n"
        "local t = Test.new()\n"
        "t:expect(1 == 1, 'require works with shipped file')\n"
        "t:expect(1 == 2, 'this must fail')\n"
        "local gt = fluaTest.new()\n"
        "gt:expect(true, 'global spelling works')\n"
        "t:finish()\n"
    )
    result = _run("qa.lua", cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PASS: require works with shipped file" in result.stdout
    assert "FAIL: this must fail" in result.stdout
    assert "PASS: global spelling works" in result.stdout
    assert "failures: 1" in result.stdout


def test_flua_test_noop_without_flua_runtime() -> None:
    # the HC3 path: shipped as a QA file on a real controller there is no
    # _FLUA, so every assertion is inert — no printing, no counting,
    # finish() returns 0. Model it with a bare env (package present, like
    # the HC3's stdlib).
    from flua.engine import LuaEngine

    lib = REPO_ROOT / "src" / "flua" / "lua" / "lib" / "flua-test.lua"
    engine = LuaEngine()
    lua = engine.lua_runtime()
    result = lua.execute(
        "-- a full Lua env MINUS flua's _FLUA: the real-HC3 model\n"
        "local env = setmetatable({ package = { preload = {} } }, { __index = _G })\n"
        "env._FLUA = false  -- shadow the runtime's _FLUA (a table -> asserts on)\n"
        "local chunk = assert(loadfile('" + str(lib) + "', 'bt', env))\n"
        "local Test = chunk()\n"
        "local t = Test.new()\n"
        "assert(t:expect(1 == 2, 'x') == false)  -- returns the condition\n"
        "assert(t:assert_eq({a=1}, {a=2}, 'x') == true)\n"
        "assert(t:assert_json('{bad', 'x') == true)\n"
        "assert(t:results().failures == 0)       -- nothing counted\n"
        "assert(t:finish() == 0)                 -- no summary, no exit\n"
        "assert(env.fluaTest == Test)            -- the shared-file global\n"
        "assert(env.package.preload['flua-test']() == Test)  -- HC3 require\n"
        "return true"
    )
    assert result is True


def test_tool_ui_renders_elements(tmp_path) -> None:
    (tmp_path / "qa.lua").write_text(
        "--%%name:uitool\n"
        "--%%type:com.fibaro.binarySwitch\n"
        '--%%u:{label="l1",text="Status"}\n'
        '--%%u:{button="B1",text="Press me",onReleased="fopp"}\n'
        '--%%u:{slider="s1",text="Level",min="0",max="100",value="50",onChanged="slide"}\n'
        '--%%u:{select="sel1",text="Pick",value="11",options={{type="option",text="One",value="11"}}}\n'
        "-- --------------- EOH ---------------\n"
        "function QuickApp:fopp() end function QuickApp:slide() end\n"
        "function QuickApp:onInit() end\n"
    )
    result = _run("--tool", "ui", "qa.lua", cwd=tmp_path, nogreet=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'QA "uitool" (com.fibaro.binarySwitch)' in result.stdout
    assert 'label l1 "Status"' in result.stdout
    assert 'button B1 "Press me" -> onReleased=fopp' in result.stdout
    assert 'slider s1 "Level" [0..100] = 50 -> onChanged=slide' in result.stdout
    assert 'select sel1 "Pick" = {11} [One=11] -> onToggled' in result.stdout


def test_multi_qa_exit_aggregation(tmp_path) -> None:
    # a failing QA in a multi-QA run must fail the process (last failing wins)
    (tmp_path / "ok.lua").write_text("function QuickApp:onInit() exit(0) end\n")
    (tmp_path / "bad.lua").write_text("function QuickApp:onInit() exit(7) end\n")
    result = _run("ok.lua", "bad.lua", cwd=tmp_path)
    assert result.returncode == 7, result.stdout + result.stderr
    assert "QA bad (5001) exited with code 7" in result.stderr


def test_verdict_line_only_for_failures(tmp_path) -> None:
    (tmp_path / "ok.lua").write_text("function QuickApp:onInit() exit(0) end\n")
    result = _run("ok.lua", cwd=tmp_path)
    assert result.returncode == 0
    assert "exited with code" not in result.stderr
