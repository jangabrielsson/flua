"""Multi-file QAs: --%%file loading order and the /quickApp/* files API."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine

REPO_ROOT = Path(__file__).resolve().parent.parent

REPO_ROOT = Path(__file__).resolve().parent.parent


async def _run_qas(files: dict[str, str], sleep: float = 0.6, capsys=None) -> str:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        paths = {}
        for name, content in files.items():
            path = Path(d) / name
            path.write_text(content)
            paths[name] = str(path)
        engine = LuaEngine()
        await engine.start()
        try:
            for name in files:
                engine.load_qa_file(paths[name])
            await asyncio.sleep(sleep)
        finally:
            await engine.stop()
    return capsys.readouterr().out


@pytest.mark.asyncio
async def test_extra_files_load_in_declaration_order(capsys) -> None:
    out = await _run_qas(
        {
            "main.lua": (
                "--%%file:b.lua,b\n"
                "--%%file:a.lua,a\n"
                "-- --------------- EOH ---------------\n"
                "function QuickApp:onInit()\n"
                "  print('ORDER', ORDER)\n"
                "  print('HELPER', sharedHelper())\n"
                "end\n"
            ),
            "b.lua": 'ORDER = (ORDER or "") .. "b"\n',
            "a.lua": ('ORDER = (ORDER or "") .. "a"\nfunction sharedHelper() return 42 end\n'),
        },
        capsys=capsys,
    )
    assert "ORDER ba" in out  # b declared first, so it loads first
    assert "HELPER 42" in out


@pytest.mark.asyncio
async def test_quickapp_files_list_and_get(capsys) -> None:
    out = await _run_qas(
        {
            "main.lua": "--%%file:lib.lua,lib\nprint('X', _FLUA.config.files[1].name)\n",
            "lib.lua": "LIB = true\n",
        },
        capsys=capsys,
    )
    assert "X lib" in out


@pytest.mark.asyncio
async def test_quickapp_rest_routes_and_restart(tmp_path, capsys) -> None:
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%file:lib.lua,lib\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function() print('OLD TIMER') end, 1000)\n"
        "function QuickApp:onInit()\n"
        "  print('MODE', MODE)\n"
        "end\n"
    )
    lib = tmp_path / "lib.lua"
    lib.write_text('MODE = "v1"\n')
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.2)
        out = capsys.readouterr().out  # drain the initial run's output
        assert "MODE v1" in out

        api = engine.api
        files, status = api.dispatch("GET", "/quickApp/5000/files")
        assert status == 200
        names = [(f["name"], f["isMain"]) for f in files]
        assert ("main", True) in names and ("lib", False) in names

        entry, status = api.dispatch("GET", "/quickApp/5000/files/lib")
        assert status == 200 and entry["content"] == 'MODE = "v1"\n'

        # updating main is forbidden offline (it lives on the user's disk)
        assert api.dispatch("PUT", "/quickApp/5000/files/main", {"content": "x"}) == (
            None,
            403,
        )

        # updating an extra file restarts the QA
        assert (
            api.dispatch("PUT", "/quickApp/5000/files/lib", {"content": 'MODE = "v2"\n'})[1] == 200
        )
        await asyncio.sleep(0.3)
        out = capsys.readouterr().out
        assert "MODE v2" in out
        assert "OLD TIMER" not in out  # the old QA's 1s timer was cancelled

        # deleting the file restarts without it
        assert api.dispatch("DELETE", "/quickApp/5000/files/lib") == (None, 200)
        await asyncio.sleep(0.3)
        out = capsys.readouterr().out
        assert "MODE" in out  # restart happened; MODE is now nil
        assert "OLD TIMER" not in out
        assert api.dispatch("DELETE", "/quickApp/5000/files/main") == (None, 404)
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_quickapp_export(tmp_path, capsys) -> None:
    main = tmp_path / "main.lua"
    main.write_text("--%%name:export-me\n--%%file:lib.lua,lib\nprint('hi')\n")
    lib = tmp_path / "lib.lua"
    lib.write_text("LIB = 1\n")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.2)
        exported, status = engine.api.dispatch("GET", "/quickApp/export/5000")
        assert status == 200
        assert exported["type"] == "com.fibaro.binarySwitch"  # device type, not "QuickApp"
        assert exported["name"] == "export-me"
        assert exported["apiVersion"] == "1.3"
        # the device's interfaces travel, minus the system-managed quickApp
        assert "light" in exported["initialInterfaces"]
        assert "quickApp" not in exported["initialInterfaces"]
        # dynamic properties (value, state, ...) never travel in the package
        props = exported["initialProperties"]
        assert "value" not in props and "deviceControlType" not in props
        assert "userDescription" in props  # the real export's field set
        assert "model" not in props  # dynamic fields never travel
        assert isinstance(props["quickAppVariables"], list)
        files = exported["files"]
        assert [f["name"] for f in files] == ["main", "lib"]
        assert files[0]["isMain"] is True and files[1]["isMain"] is False
        assert files[0]["isOpen"] is False
        assert "type" not in files[0]  # the real format has no file type
        assert files[1]["content"] == "LIB = 1\n"
        # export must round-trip through JSON (it is the .fqa body)
        json.loads(json.dumps(exported))
        assert engine.api.dispatch("GET", "/quickApp/export/9999") == (None, 404)
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_quickapp_export_filters_and_arrayifies(tmp_path, capsys) -> None:
    main = tmp_path / "main.lua"
    main.write_text("print('x')\n")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(
            str(main),
            None,
            {
                "properties": {
                    "value": True,  # dynamic — must not travel
                    "userDescription": "v2",  # whitelisted — travels
                    "uiCallbacks": [{"name": "__private"}, {"name": "btn1"}],
                }
            },
            str(main),
        )
        await asyncio.sleep(0.2)
        exported, status = engine.api.dispatch("GET", "/quickApp/export/5000")
        assert status == 200
        props = exported["initialProperties"]
        assert "value" not in props
        assert props["userDescription"] == "v2"
        assert props["uiCallbacks"] == [{"name": "btn1"}]  # __-prefixed stripped
        for key in ("quickAppVariables", "uiView", "supportedDeviceRoles"):
            if key == "supportedDeviceRoles":
                assert key not in props  # filtered — the real export lacks it
            else:
                assert isinstance(props[key], list)
        # the package must round-trip through import and keep the properties
        device, status = engine.api.dispatch("POST", "/quickApp/import", exported)
        assert status == 200
        imported_device = engine.api.state.devices[device["id"]]
        assert imported_device["properties"]["userDescription"] == "v2"
        assert imported_device["properties"]["uiCallbacks"] == [{"name": "btn1"}]
    finally:
        await engine.stop()


def test_example_multifile_runs() -> None:
    # fully deterministic: the extra file loads and the helper answers
    result = subprocess.run(
        [sys.executable, "-m", "flua", "examples/multifile.lua"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "helper says: loaded in order" in result.stdout


@pytest.mark.asyncio
async def test_quickapp_import_runs_the_qa(tmp_path, capsys) -> None:
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id, status = engine.api.dispatch(
            "POST",
            "/quickApp/import",
            {
                "type": "QuickApp",
                "name": "imported",
                "files": [
                    {
                        "name": "main",
                        "type": "lua",
                        "isMain": True,
                        "content": (
                            "function QuickApp:onInit()\n  print('IMPORTED', helper())\nend\n"
                        ),
                    },
                    {
                        "name": "util",
                        "type": "lua",
                        "isMain": False,
                        "content": "function helper() return 'works' end\n",
                    },
                ],
            },
        )
        assert status == 200
        assert qa_id["id"] == 5000  # DeviceDto, like the HC3
        qa_id = qa_id["id"]
        await asyncio.sleep(0.4)
        out = capsys.readouterr().out
        assert "IMPORTED works" in out
        files, status = engine.api.dispatch("GET", f"/quickApp/{qa_id}/files")
        assert status == 200
        assert [f["name"] for f in files] == ["main", "util"]
        assert engine.qa_timer_count(qa_id) == 0
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_named_property_directives(tmp_path, capsys) -> None:
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%uid:qa-uuid-123\n"
        "--%%description:my little QA\n"
        "--%%model:model-x\n"
        "--%%build:7\n"
        "--%%manufacturer:fibaro\n"
        "--%%property:value=true\n"
        "-- --------------- EOH ---------------\n"
        "setTimeout(function()\n"
        "  local props = api.get('/devices/'.._FLUA.qaId).properties\n"
        "  print('PROPS', props.quickAppUuid, props.userDescription, props.model)\n"
        "  print('MORE', props.buildNumber, props.manufacturer, props.value)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.3)
        out = capsys.readouterr().out
        assert "PROPS qa-uuid-123 my little QA model-x" in out
        assert "MORE 7 fibaro true" in out
        device = engine.api.state.devices[5000]
        assert device["properties"]["quickAppUuid"] == "qa-uuid-123"
        assert device["properties"]["userDescription"] == "my little QA"
        assert device["properties"]["model"] == "model-x"
        assert device["properties"]["buildNumber"] == 7  # a number, not "7"
        assert device["properties"]["manufacturer"] == "fibaro"
        assert device["properties"]["value"] is True
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_var_directive_initializes_quickapp_variables(tmp_path, capsys) -> None:
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%var:greeting='hello'\n"  # expressions now: strings need quotes
        "--%%var:count=42\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  print('VARS', self:getVariable('greeting'), self:getVariable('count'), "
        "self:getVariable('missing'))\n"
        "  self:setVariable('greeting', 'hi again')\n"
        "  print('UPDATED', self:getVariable('greeting'))\n"
        "  print('TYPE', type(self:getVariable('count')))\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.3)
        out = capsys.readouterr().out
        assert "VARS hello 42" in out
        assert "UPDATED hi again" in out
        assert "TYPE number" in out  # 42 evaluates as a number, not "42"
        # persisted in the sim: the device property carries the variables
        device = engine.api.state.devices[5000]
        names = {v["name"]: v["value"] for v in device["properties"]["quickAppVariables"]}
        assert names == {"greeting": "hi again", "count": 42}
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_quickapp_import_returns_id_through_lua_api(tmp_path, capsys) -> None:
    # scalar api returns (the new QA id) must cross the bridge as numbers
    loader = tmp_path / "loader.lua"
    loader.write_text(
        "setTimeout(function()\n"
        "  local fqa = {\n"
        "    type = 'QuickApp', name = 'from-api',\n"
        "    files = { { name = 'main', isMain = true, content = \"print('API QA')\\n\" } },\n"
        "  }\n"
        "  local dev, status = api.post('/quickApp/import', fqa)\n"
        "  print('IMPORTED', type(dev) == 'table', status, dev.id)\n"
        "end, 20)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(loader), None, {}, str(loader))
        await asyncio.sleep(0.5)
        out = capsys.readouterr().out
        assert "IMPORTED true 200 5001" in out
        assert "API QA" in out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_quickapp_import_from_base64(tmp_path, capsys) -> None:
    import base64

    fqa = {
        "type": "QuickApp",
        "name": "b64",
        "files": [{"name": "main", "isMain": True, "content": "print('B64 QA')\n"}],
    }
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id, status = engine.api.dispatch(
            "POST",
            "/quickApp/import",
            {"file": base64.b64encode(json.dumps(fqa).encode()).decode()},
        )
        assert status == 200 and qa_id["id"] == 5000
        qa_id = qa_id["id"]
        await asyncio.sleep(0.4)
        assert "B64 QA" in capsys.readouterr().out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_quickapp_import_validation(tmp_path, capsys) -> None:
    engine = LuaEngine()
    await engine.start()
    try:
        # no main file
        assert engine.api.dispatch(
            "POST",
            "/quickApp/import",
            {"files": [{"name": "util", "content": "x = 1\n"}]},
        ) == (None, 400)
        # not a package at all
        assert engine.api.dispatch("POST", "/quickApp/import", {"file": "!!not-base64!!"}) == (
            None,
            400,
        )
        # encrypted export is not supported (Fibaro-specific)
        assert engine.api.dispatch("POST", "/quickApp/export/5000", {"encrypted": True}) == (
            None,
            501,
        )
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_quickapp_export_import_roundtrip(tmp_path, capsys) -> None:
    main = tmp_path / "main.lua"
    main.write_text("--%%name:roundtrip\n--%%file:lib.lua,lib\nprint('RT', LIB)\n")
    lib = tmp_path / "lib.lua"
    lib.write_text("LIB = 99\n")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.3)
        assert "RT 99" in capsys.readouterr().out
        exported, status = engine.api.dispatch("GET", "/quickApp/export/5000")
        assert status == 200
        device, status = engine.api.dispatch("POST", "/quickApp/import", exported)
        assert status == 200 and device["id"] == 5001
        await asyncio.sleep(0.4)
        assert "RT 99" in capsys.readouterr().out  # the imported copy runs too
    finally:
        await engine.stop()


def test_quickapp_available_types() -> None:
    from flua.api import Api

    api = Api(engine=LuaEngine())
    data, status = api._quickapp("GET", ["quickApp", "availableTypes"], None)
    assert status == 200
    assert any(t["type"] == "com.fibaro.binarySwitch" for t in data)
    assert all(set(t) == {"type", "label"} for t in data)


@pytest.mark.asyncio
async def test_quickapp_create_device(tmp_path, capsys) -> None:
    engine = LuaEngine()
    await engine.start()
    try:
        device, status = engine.api.dispatch(
            "POST",
            "/quickApp",
            {
                "name": "created-qa",
                "type": "com.fibaro.binarySwitch",
                "roomId": 3,
                "initialProperties": {"model": "m1"},
                "initialInterfaces": [],
                "initialView": {},
            },
        )
        assert status == 200
        assert device["id"] == 5000
        assert device["name"] == "created-qa"
        assert device["roomID"] == 3
        assert device["properties"]["model"] == "m1"
        # the QA runs (empty main) and its files API shows just main
        files, status = engine.api.dispatch("GET", "/quickApp/5000/files")
        assert status == 200
        assert [f["name"] for f in files] == ["main"]
        assert engine.api.dispatch("POST", "/quickApp", {"type": "com.fibaro.binarySwitch"}) == (
            None,
            400,
        )  # name required
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_quickapp_files_create_and_bulk_update(tmp_path, capsys) -> None:
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%file:lib.lua,lib\n-- --------------- EOH ---------------\nprint('M', LIB)\n"
    )
    lib = tmp_path / "lib.lua"
    lib.write_text("LIB = 1\n")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.3)
        assert "M 1" in capsys.readouterr().out
        # POST /files creates a new (empty) file
        entry, status = engine.api.dispatch(
            "POST", "/quickApp/5000/files", {"name": "util", "type": "lua"}
        )
        assert status == 200 and entry["name"] == "util" and entry["content"] == ""
        # PUT /files updates several files in one call, restarting once
        entries, status = engine.api.dispatch(
            "PUT",
            "/quickApp/5000/files",
            [
                {"name": "lib", "content": "LIB = 2\n"},
                {"name": "util", "content": "LIB = (LIB or '') .. 'u'\n"},
            ],
        )
        assert status == 200
        assert {f["name"] for f in entries} == {"main", "lib", "util"}
        await asyncio.sleep(0.3)
        out = capsys.readouterr().out
        assert "M 2u" in out  # both files loaded in declaration order
        assert engine.api.dispatch("PUT", "/quickApp/5000/files", "not-a-list") == (None, 400)
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_var_expressions_evaluate_lua_values(tmp_path, capsys, monkeypatch) -> None:
    # --%%var values are Lua expressions evaluated with {config, os} in scope
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # isolate from the real ~/.flua.lua
    (tmp_path / ".flua.lua").write_text(
        "return { color = 'red', user = 'alice', nested = { n = 1 } }\n"
    )
    monkeypatch.setenv("QA_TOKEN", "tok-123")
    monkeypatch.chdir(tmp_path)
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%var:token=os.getenv('QA_TOKEN')\n"
        "--%%var:color=config.color\n"
        "--%%var:count=42\n"
        "--%%var:tbl={a=1,b='two'}\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  print('TOKEN', self:getVariable('token'))\n"
        "  print('COLOR', self:getVariable('color'))\n"
        "  print('COUNT', type(self:getVariable('count')), self:getVariable('count'))\n"
        "  print('TBL', self:getVariable('tbl').a, self:getVariable('tbl').b)\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.3)
        out = capsys.readouterr().out
        assert "TOKEN tok-123" in out
        assert "COLOR red" in out
        assert "COUNT number 42" in out
        assert "TBL 1 two" in out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_lua_config_merges_into_flua_config(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".flua.lua").write_text("return { user = 'alice', pwd = 'secret' }\n")
    monkeypatch.chdir(tmp_path)
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%name:from-annotation\n"  # annotations win over the file
        "-- --------------- EOH ---------------\n"
        "print('CFG', _FLUA.config.user, _FLUA.config.pwd, _FLUA.config.name)\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.3)
        assert "CFG alice secret from-annotation" in capsys.readouterr().out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_legacy_plua_config(tmp_path, capsys, monkeypatch) -> None:
    # ~/.plua/config.lua still works when no .flua.lua exists anywhere
    home = tmp_path / "home"
    legacy = home / ".plua"
    legacy.mkdir(parents=True)
    (legacy / "config.lua").write_text("return { legacy = 'yes' }\n")
    monkeypatch.setenv("HOME", str(home))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    main = work / "main.lua"
    main.write_text("print('LEGACY', _FLUA.config.legacy)\n")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.3)
        assert "LEGACY yes" in capsys.readouterr().out
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_bad_var_expression_fails_startup(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%var:broken=os.no_such_function()\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit() print('SHOULD NOT RUN') end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.3)
        out = capsys.readouterr().out
        assert "error in --%%var:broken: os.no_such_function()" in out
        assert "SHOULD NOT RUN" not in out  # onInit never ran
        assert engine.exit_code == 1
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_var_expression_nil_result_is_fine(tmp_path, capsys, monkeypatch) -> None:
    # evaluating to nil (missing config key, unset env) is NOT an error —
    # the variable simply stays unset. Only faulty expressions (syntax or
    # runtime errors like indexing a nil table) hard-fail.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%var:maybe=config.nothere\n"
        "--%%var:env=os.getenv('MISSING_ENV')\n"
        "--%%var:fine=1+1\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  print('VARS', self:getVariable('fine'), self:getVariable('maybe'), "
        "self:getVariable('env'))\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.load_qa_file(str(main))
        await asyncio.sleep(0.3)
        out = capsys.readouterr().out
        assert "error in --%%var" not in out
        assert "VARS 2" in out  # fine=2; the nil vars are simply absent
        assert engine.exit_code == 0
    finally:
        await engine.stop()
