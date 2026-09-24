"""Device type skeletons: catalog loading, scrubbing, and QA integration."""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.api import Api
from flua.devices import catalog_types, skeleton_for
from flua.engine import LuaEngine


def test_catalog_has_expected_types() -> None:
    types = catalog_types()
    assert "com.fibaro.binarySwitch" in types
    assert "com.fibaro.remoteColorController" in types
    assert len(types) > 100


def test_skeleton_for_known_type() -> None:
    skeleton = skeleton_for("com.fibaro.remoteColorController")
    assert skeleton is not None
    assert "light" in skeleton["interfaces"]
    assert "quickApp" in skeleton["interfaces"]
    assert "turnOn" in skeleton["actions"]
    assert skeleton["parentId"] == 0
    assert skeleton["roomID"] == 219  # the HC3 default room
    assert skeleton["isPlugin"] is True
    # identity fields from the capture must not leak into the skeleton
    for field in ("id", "name", "created", "modified", "sortOrder"):
        assert field not in skeleton


def test_skeleton_for_unknown_type() -> None:
    assert skeleton_for("com.fibaro.doesNotExist") is None
    assert skeleton_for(None) is None
    assert skeleton_for("") is None


def test_skeleton_scrubs_instance_data() -> None:
    skeleton = skeleton_for("com.fibaro.alphatechFarfisa")
    assert skeleton is not None
    properties = skeleton["properties"]
    for key in ("sipUserPassword", "password", "ip", "quickAppUuid", "log", "logTemp"):
        assert key not in properties


def test_skeleton_copies_are_independent() -> None:
    first = skeleton_for("com.fibaro.binarySwitch")
    second = skeleton_for("com.fibaro.binarySwitch")
    assert first is not second  # deep copies, not the cached entry
    first["properties"]["zz_marker"] = "mutated"
    assert "zz_marker" not in second["properties"]
    # and the cached catalog entry is untouched
    again = skeleton_for("com.fibaro.binarySwitch")
    assert "zz_marker" not in again["properties"]


def test_register_qa_defaults_to_binary_switch_skeleton() -> None:
    api = Api()
    api.register_qa(5000, "qa", None, {})
    device = api.state.devices[5000]
    assert device["type"] == "com.fibaro.binarySwitch"
    assert "light" in device["interfaces"]  # from the catalog skeleton
    assert "value" in device["properties"]  # catalog defaults present
    assert "quickAppVariables" in device["properties"]


def test_register_qa_unknown_type_raises() -> None:
    api = Api()
    with pytest.raises(ValueError, match="unknown device type"):
        api.register_qa(5000, "qa", "com.no.such.type", {})


def test_cli_unknown_type_is_an_error(tmp_path) -> None:
    script = tmp_path / "bad.lua"
    script.write_text("--%%type:com.no.such.type\nprint('x')\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "unknown device type" in result.stderr


def test_register_qa_uses_type_skeleton() -> None:
    api = Api()
    api.register_qa(5000, "color", "com.fibaro.remoteColorController", {"value": True})
    data, status = api.dispatch("GET", "/devices/5000")
    assert status == 200
    assert data["name"] == "color"  # QA identity wins over the skeleton
    assert data["type"] == "com.fibaro.remoteColorController"
    assert "light" in data["interfaces"]
    assert "quickApp" in data["interfaces"]
    assert data["properties"]["value"] is True  # config overlays skeleton defaults
    assert "deviceControlType" in data["properties"]  # skeleton default preserved


def test_create_child_device_uses_type_skeleton() -> None:
    api = Api()
    api.register_qa(5000, "qa", None, {})
    child, status = api.dispatch(
        "POST",
        "/plugins/createChildDevice",
        {
            "name": "dimmer",
            "type": "com.fibaro.remoteColorController",
            "parentId": 5000,
            "initialProperties": {"value": 10},
            "initialInterfaces": ["light"],
        },
    )
    assert status == 201
    assert child["properties"]["value"] == 10  # initialProperties win
    assert "deviceControlType" in child["properties"]  # skeleton default present
    assert child["interfaces"] == ["light"]  # the lib controls child interfaces


@pytest.mark.asyncio
async def test_qa_instance_built_from_type_skeleton(tmp_path, capsys) -> None:
    # The Lua QuickApp instance must see the same enriched device the API
    # serves: type skeleton defaults + interfaces.
    script = tmp_path / "color.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  print('IF', self:hasInterface('light'), self.type)\n"
        "  print('CTRL', self.properties.deviceControlType)\n"
        "end\n"
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(
            str(script), None, {"type": "com.fibaro.remoteColorController"}, str(script)
        )
        await asyncio.sleep(0.3)
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "IF true com.fibaro.remoteColorController" in out
    assert "CTRL 2" in out


@pytest.mark.asyncio
async def test_qa_remove_child_device(tmp_path, capsys) -> None:
    # the HC3 lifecycle: createChildDevice then
    # api.delete("/plugins/removeChildDevice/"..id) drops the child locally
    # (offline there is no HC3 to mirror to)
    script = tmp_path / "kids.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  local c = self:createChildDevice({name='c1', type='com.fibaro.binarySwitch'})\n"
        "  print('CREATED', c.id)\n"
        "  local stat = select(2, api.delete('/plugins/removeChildDevice/'..c.id))\n"
        "  print('DELETED', stat)\n"
        "  local kids = api.get('/devices?parentId='..self.id)\n"
        "  print('LEFT', #kids)\n"
        "  local gone = select(2, api.delete('/plugins/removeChildDevice/'..c.id))\n"
        "  print('AGAIN', gone)\n"
        "  local parent = select(2, api.delete('/plugins/removeChildDevice/'..self.id))\n"
        "  print('PARENT', parent)\n"
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
    assert "CREATED" in out
    assert "DELETED 204" in out  # the child was removed
    assert "LEFT 0" in out  # and no longer listed under the parent
    assert "AGAIN 404" in out  # unknown ids 404
    assert "PARENT 501" in out  # the QA itself is not a child
