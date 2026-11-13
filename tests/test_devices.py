"""Device type skeletons: catalog loading, scrubbing, and QA integration."""

import asyncio
import json
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
    assert "com.fibaro.pko" in types  # capture-only, kept as the fallback
    assert len(types) >= 189  # the schema; the capture only adds fallback types


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
    with pytest.raises(ValueError, match="unknown device type") as info:
        api.register_qa(5000, "qa", "com.no.such.type", {})
    # the error is actionable: it points at the catalog
    assert "flua --tool catalog" in str(info.value)


def test_register_qa_typo_suggests_close_matches() -> None:
    api = Api()
    with pytest.raises(ValueError, match="did you mean") as info:
        api.register_qa(5000, "qa", "com.fibaro.binaryswitc", {})
    assert "com.fibaro.binarySwitch" in str(info.value)


def test_cli_unknown_type_is_an_error(tmp_path) -> None:
    script = tmp_path / "bad.lua"
    script.write_text("--%%type:com.no.such.type\nprint('x')\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "unknown device type" in result.stderr
    assert "flua --tool catalog" in result.stderr


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
    assert status == 200  # the HC3 returns 200 (spec: 200/400/500)
    assert child["properties"]["value"] == 10  # initialProperties win
    assert "deviceControlType" in child["properties"]  # skeleton default present
    assert child["interfaces"] == ["light"]  # the lib controls child interfaces


# -- type schemas (the distilled HC3 type/interface artifact) -------------------


KNOWN_PROPERTY_TYPES = {
    "bool",
    "int",
    "real",
    "string",
    "array",
    "object",
    "temperature",
    "weather",
    "iOS_device",
}


def test_type_schemas_are_self_consistent() -> None:
    from flua.devices import type_schemas

    schemas = type_schemas()
    types = schemas["types"]
    interfaces = schemas["interfaces"]
    assert len(types) > 100 and len(interfaces) > 100
    # every base type resolves and inheritance never cycles
    for name, entry in types.items():
        seen = set()
        current = entry.get("baseType")
        while current:
            assert current in types, f"{name}: unknown baseType {current}"
            assert current not in seen, f"{name}: inheritance cycle via {current}"
            seen.add(current)
            current = types[current].get("baseType")
        # every referenced interface exists; property types are known
        for interface in entry.get("interfaces") or []:
            assert interface in interfaces, f"{name}: unknown interface {interface}"
        for prop, spec in (entry.get("properties") or {}).items():
            ptype = spec.get("type", "string")
            assert ptype in KNOWN_PROPERTY_TYPES or ptype.startswith("com.fibaro."), (
                f"{name}.{prop}: unexpected type {ptype}"
            )
    # the interface layer is conflict-free (mined from the sources): no
    # interface re-declares a property with a different type than another
    # interface or than any type that carries it — pin it, so extraction
    # regressions cannot silently introduce contradictory specs
    iface_props: dict[str, dict[str, str]] = {}
    for iname, ischema in interfaces.items():
        for prop, spec in (ischema.get("properties") or {}).items():
            ptype = spec.get("type", "string")
            prior = iface_props.get(prop)
            assert prior is None or prior[0] == ptype, (
                f"interface conflict: {prop} declared {prior[0]} ({prior[1]}) and {ptype} ({iname})"
            )
            iface_props[prop] = (ptype, iname)
    for name, entry in types.items():
        declared = set(entry.get("interfaces") or [])
        for prop, spec in (entry.get("properties") or {}).items():
            ptype = spec.get("type", "string")
            for iname in declared:
                ischema = interfaces.get(iname)
                if not ischema or prop not in (ischema.get("properties") or {}):
                    continue
                itype = ischema["properties"][prop].get("type", "string")
                assert itype == ptype, (
                    f"type/interface conflict: {name}.{prop} declares {ptype} "
                    f"but interface {iname} declares {itype}"
                )


def test_schema_for_known_type() -> None:
    from flua.devices import schema_for

    skeleton = schema_for("com.fibaro.binarySwitch")
    assert skeleton is not None
    # the base-type chain is flattened in: com.fibaro.device's dead/log
    # plus the type's own declarations
    assert "dead" in skeleton["properties"]
    assert "value" in skeleton["properties"]
    # the type's interface list, with defaults from the declaration
    assert skeleton["interfaces"] == ["light", "autoTurnOff"]
    assert skeleton["properties"]["deviceIcon"] == 301  # overrides device's 389
    assert skeleton["properties"]["deviceRole"] == "Light"  # in the enum
    assert skeleton["actions"]["turnOn"] == 1  # the HC3 serves name -> argc
    assert schema_for("com.fibaro.doesNotExist") is None
    assert schema_for(None) is None


@pytest.mark.asyncio
async def test_qa_interface_directive_applies_schema() -> None:
    # --%%interface:autoTurnOff — the QA's device gets the interface's
    # properties (at their defaults) and action metadata, like the REST
    # route
    import tempfile

    from flua.engine import LuaEngine

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "qa.lua"
        script.write_text(
            "--%%name:IfaceQA\n--%%interface:autoTurnOff\nfunction QuickApp:onInit() exit(0) end\n"
        )
        engine = LuaEngine()
        await engine.start()
        try:
            qa_id, err = engine.load_qa_file(str(script))
            assert err is None, err
            device = engine.api.state.devices[qa_id]
            assert "autoTurnOff" in device["interfaces"]
            assert device["properties"]["autoOffTimestamp"] == 0
            assert device["properties"]["autoOffDefaultTime"] == 900
            assert device["actions"]["setAutoOff"] == 3
        finally:
            await engine.stop()


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


def test_qwikchild_example_self_tests() -> None:
    # examples/qwikchildtest.lua is the living fixture: qwikchild children
    # driven through their UI (button, slider) and the updateChildren pattern
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/qwikchildtest.lua"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for line in (
        "children created",
        "button press updated childB's label",
        "slider set childA's value property",
        "updateChildren refreshed childA's label",
    ):
        assert f"PASS: {line}" in result.stdout
    assert "failures: 0" in result.stdout


def test_skeleton_falls_back_to_hierarchy_ancestor() -> None:
    # com.fibaro.FGD223 is not in the catalog, but the offline hierarchy
    # (devices/hierarchy.json, distilled from the HC3) links it to
    # com.fibaro.device — its skeleton serves the unknown type
    skeleton = skeleton_for("com.fibaro.FGD223")
    assert skeleton is not None
    assert skeleton["type"] == "com.fibaro.device"
    # a type the hierarchy never heard of is still unknown
    assert skeleton_for("com.fibaro.notARealType") is None
    assert skeleton_for(None) is None


def test_qa_with_hierarchy_known_type_runs(tmp_path, capsys) -> None:
    # a QA declaring a type newer than the catalog capture resolves to its
    # hierarchy ancestor and keeps its own type on the device
    script = tmp_path / "qa.lua"
    script.write_text(
        "--%%type:com.fibaro.FGD223\n"
        "print('TYPE', api.get('/devices/'.._FLUA.qaId).type)\n"
        "exit(0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TYPE com.fibaro.FGD223" in result.stdout


def test_qa_with_unknown_type_still_errors(tmp_path) -> None:
    script = tmp_path / "qa.lua"
    script.write_text("--%%type:com.fibaro.notARealType\nexit(0)\n")
    result = subprocess.run(
        [sys.executable, "-m", "flua", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "unknown device type" in result.stderr


def test_icon_manifest_covers_catalog() -> None:
    # scripts/extract_icon_files.py: every device icon set in the checked-in
    # catalog (icons.json) resolves to its state file names, so the viewer
    # can render any deviceIcon offline (the image bytes live on the HC3 /
    # in the webroot dump — the manifest is facts only)
    root = Path(__file__).resolve().parent.parent
    catalog = json.loads((root / "src/flua/devices/icons.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (root / "src/flua/devices/icon_manifest.json").read_text(encoding="utf-8")
    )
    files = manifest["files"]
    assert manifest["meta"]["firmware"]
    for entry in catalog["data"]["device"]:
        names = files.get(entry["iconSetName"])
        assert names, f"no icon files for set {entry['iconSetName']}"
        assert all(isinstance(name, str) for name in names)


def test_icon_cache_dir_env_override(tmp_path, monkeypatch) -> None:
    # the icon cache is machine-level; FLUA_ICON_DIR overrides it (tests,
    # portable setups)
    from flua.devices import icon_cache_dir

    monkeypatch.setenv("FLUA_ICON_DIR", str(tmp_path / "icons"))
    assert icon_cache_dir() == tmp_path / "icons"


def test_icon_file_resolves_only_inside_cache(tmp_path, monkeypatch) -> None:
    # the /flua/icons channel: cached icon bytes with the right content
    # type; traversal, separators and unknown names resolve to nothing
    from flua.devices import icon_file

    monkeypatch.setenv("FLUA_ICON_DIR", str(tmp_path / "icons"))
    folder = tmp_path / "icons" / "ButtonSwitchV2"
    folder.mkdir(parents=True)
    (folder / "ButtonSwitchV20.svg").write_bytes(b"<svg>off</svg>")
    assert icon_file("ButtonSwitchV2", "ButtonSwitchV20.svg") == (
        b"<svg>off</svg>",
        "image/svg+xml",
    )
    # a miss falls back to the sibling extension (png <-> svg): sets whose
    # declared .png slot is an SVG body (dropped as a placeholder) render
    # from the cached .svg, and vice versa
    assert icon_file("ButtonSwitchV2", "ButtonSwitchV20.png") == (
        b"<svg>off</svg>",
        "image/svg+xml",
    )
    (folder / "ButtonSwitchV20.svg").unlink()
    (folder / "ButtonSwitchV20.png").write_bytes(b"\x89PNG")
    assert icon_file("ButtonSwitchV2", "ButtonSwitchV20.svg") == (b"\x89PNG", "image/png")
    assert icon_file("ButtonSwitchV2", "missing.svg") is None
    # traversal and separators are refused by the name pattern / resolution
    assert icon_file("ButtonSwitchV2", "../secret") is None
    assert icon_file("..", "secret.svg") is None
    assert icon_file("ButtonSwitchV2/other", "x.svg") is None


def test_type_icon_family_resolves_through_the_hierarchy() -> None:
    # product types inherit their family from the nearest known ancestor —
    # the HC3 registers user icon sets under the concrete type
    from flua.devices import type_icon_family

    assert type_icon_family("com.fibaro.binarySwitch") == "binary"
    assert type_icon_family("com.fibaro.FGWDS221") == "binary"  # child of binarySwitch
    assert type_icon_family("com.fibaro.motionSensor") == "binary"
    assert type_icon_family("com.fibaro.baseShutter") == "baseShutter"
    assert type_icon_family("com.fibaro.genericDevice") == "single"
    assert type_icon_family("com.fibaro.noSuchType") == "single"
    assert type_icon_family(None) == "single"


def test_local_icon_files_and_serving(tmp_path) -> None:
    # the --%%icons folder: upload-named files (icon<suffix>.<ext>) become a
    # synthetic set's <set><suffix>.<ext> names; unknown files are skipped;
    # serving translates back and refuses traversal/unknown shapes
    from flua.devices import local_icon_file, local_icon_files

    folder = tmp_path / "icons"
    folder.mkdir()
    (folder / "icon.png").write_bytes(b"\x89PNGbase")
    (folder / "icon0.png").write_bytes(b"\x89PNGoff")
    (folder / "icon100.svg").write_bytes(b"<svg>on</svg>")
    (folder / "readme.txt").write_text("skip me")

    assert local_icon_files("Local5000", folder) == [
        "Local5000.png",
        "Local50000.png",
        "Local5000100.svg",
    ]
    assert local_icon_file("Local5000", folder, "Local50000.png") == (
        b"\x89PNGoff",
        "image/png",
    )
    assert local_icon_file("Local5000", folder, "Local5000100.svg") == (
        b"<svg>on</svg>",
        "image/svg+xml",
    )
    # unknown names and traversal are refused (the set -> folder binding is
    # the caller's job; this helper is a pure name translation)
    assert local_icon_file("Local5000", folder, "Local500050.png") is None
    assert local_icon_file("Local5000", folder, "../secret") is None
    assert local_icon_file("Local5000", folder, "Local5000../../secret.png") is None
    assert local_icon_files("Local5000", tmp_path / "missing") == []


def test_icon_default_file_prefers_base_then_off_state(monkeypatch) -> None:
    # the viewer's static default per set: the base file when it exists,
    # else the 0 state, else the first file — pinned against a synthetic
    # manifest (the scraped catalog changes over firmware versions)
    import flua.devices as devices

    monkeypatch.setattr(
        devices,
        "icon_manifest",
        lambda: {
            "files": {
                "BaseSet": ["BaseSet.svg", "BaseSet0.svg"],
                "NoBaseSet": ["NoBaseSet0.svg", "NoBaseSet100.svg"],
                "EmptySet": [],
            }
        },
    )
    assert devices.icon_default_file("BaseSet", "svg") == "BaseSet.svg"
    assert devices.icon_default_file("NoBaseSet", "svg") == "NoBaseSet0.svg"
    assert devices.icon_default_file("EmptySet", "svg") is None


def test_action_params_and_overrides() -> None:
    from flua.devices import action_params

    # argc counts the implicit self: argc - 1 arguments
    assert action_params("turnOn", {"argc": 1}) == []
    assert action_params("setValue", {"argc": 2}, {}) == [{"name": "a", "type": None}]
    # named schema args fill first, placeholders take the rest
    params = action_params("setAutoOff", {"argc": 3, "args": [{"name": "time", "type": "int"}]}, {})
    assert params == [{"name": "time", "type": "int"}, {"name": "a", "type": None}]
    # the hand-maintained override wins over the schema's args
    overrides = {
        "setAutoOff": {
            "args": [{"name": "time", "type": "int"}, {"name": "manual", "type": "bool"}]
        }
    }
    params = action_params("setAutoOff", {"argc": 3, "args": []}, overrides)
    assert params == [{"name": "time", "type": "int"}, {"name": "manual", "type": "bool"}]
    # and the loaded overrides file exists with every distinct action
    from flua.devices import action_overrides

    loaded = action_overrides()
    assert len(loaded) >= 120  # argc<=1 actions stay out — nothing to name
    assert "turnOn" not in loaded  # argc=1: no arguments
    assert "setAutoOff" in loaded and loaded["setAutoOff"]["argc"] == 3
