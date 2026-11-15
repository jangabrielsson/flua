"""The recipe library: recipes/ is the QA builder's source (fetched from
the flua repo at build time); the wheel ships an offline snapshot under
setup_templates/recipes. These tests pin the index against the manifests
and prove every recipe's main.lua checks and boots."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def test_recipe_index_matches_the_manifests() -> None:
    # the checked-in index.json must equal the generator's output — a new
    # recipe without a regenerated index fails here, not in the builder
    result = subprocess.run(
        [sys.executable, "scripts/gen-recipes-index.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    index = json.loads((REPO / "recipes" / "index.json").read_text())
    ids = [recipe["id"] for recipe in index["recipes"]]
    assert len(ids) == len(set(ids)), "duplicate recipe ids"
    # every recipe folder is in the index, with its files present
    for recipe in index["recipes"]:
        folder = REPO / "recipes" / recipe["id"]
        assert (folder / "main.lua").is_file()
        assert (folder / "manifest.json").is_file()
        for param in recipe["params"]:
            assert param["kind"] in {"device", "room", "scene", "number", "text", "boolean"}
    # the offline snapshot ships with the wheel (synced by sync-skills.sh)
    snapshot = REPO / "src" / "flua" / "setup_templates" / "recipes" / "index.json"
    assert snapshot.read_bytes() == (REPO / "recipes" / "index.json").read_bytes(), (
        "run scripts/sync-skills.sh — the offline recipe snapshot drifted"
    )


def test_every_recipe_checks() -> None:
    # flua --check on every recipe main: syntax, known directives, the
    # marked --%%var params parse
    for main in sorted((REPO / "recipes").glob("*/main.lua")):
        result = subprocess.run(
            [sys.executable, "-m", "flua", "--check", str(main)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"{main}: {result.stdout} {result.stderr}"


@pytest.mark.asyncio
async def test_every_recipe_boots(tmp_path, capsys) -> None:
    # each recipe boots in the sim with its default (unset) params and
    # reports the hint instead of crashing — the recipes are living fixtures
    engine = LuaEngine()
    await engine.start()
    try:
        for main in sorted((REPO / "recipes").glob("*/main.lua")):
            qa_id, err = engine.load_qa_file(str(main))
            assert qa_id is not None and err is None, f"{main}: {err}"
    finally:
        await engine.stop()


def test_recipes_have_no_module_level_self() -> None:
    # on the real HC3 there is no `self` outside method bodies — module
    # scope must only declare locals (the sim tolerates self there; the
    # HC3 does not, and recipes are controller code first)
    for main in sorted((REPO / "recipes").glob("*/main.lua")):
        head = main.read_text(encoding="utf-8").split("function ", 1)[0]
        assert "self" not in head, f"{main}: module scope uses self"


def test_recipes_use_fibaro_call_for_device_actions() -> None:
    # device actions go through fibaro.call(id, "turnOn") — the
    # HC3-idiomatic form that stays readable for the builder audience;
    # raw api.post to the action endpoint is banned in the recipe library
    for main in sorted((REPO / "recipes").glob("*/main.lua")):
        text = main.read_text(encoding="utf-8")
        assert 'api.post("/devices/' not in text, f"{main}: raw device post"


# the builder's category selector — keep in sync with CATEGORY_ORDER in
# src/flua/setup_templates/qa_builder.html; adding a category is a
# deliberate taxonomy change, so it must be made on both sides
CATEGORY_ORDER = ["Lights", "Climate", "Alerts & alarms", "Doors & windows", "Presence"]


def test_recipes_declare_known_categories() -> None:
    used: set[str] = set()
    for folder in sorted((REPO / "recipes").iterdir()):
        if not folder.is_dir():
            continue
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        cats = manifest["categories"]
        assert cats and all(isinstance(c, str) and c for c in cats), f"{folder.name}: categories"
        used.update(cats)
    assert used == set(CATEGORY_ORDER), (
        f"recipe categories drift from the taxonomy: {sorted(used)} vs {CATEGORY_ORDER}"
    )


@pytest.mark.asyncio
async def test_heat_when_cold_reacts_to_weather() -> None:
    # the demo loop the builder's View UI tab offers: the outside
    # temperature drops below the threshold and the recipe turns the heater
    # on; above threshold + 1°C it turns it off again (the 1°C hysteresis)
    engine = LuaEngine(speed=60.0)  # 1 wall second = 60 virtual seconds
    await engine.start()
    try:
        heater, _ = engine.load_sim_device("binarySwitch")
        main = REPO / "recipes" / "heat-when-cold" / "main.lua"
        qa_id, err = engine.load_qa_file(
            str(main), [f"var:heaterId={heater}", "var:threshold=10"]
        )
        assert qa_id is not None and err is None, err
        engine.api.state.weather_overrides["Temperature"] = 5.0
        await asyncio.sleep(0.7)  # the 30s virtual poll at 60x fires in ~0.5s
        assert engine.api.state.devices[heater]["properties"]["value"] is True
        engine.api.state.weather_overrides["Temperature"] = 15.0
        await asyncio.sleep(0.7)
        assert engine.api.state.devices[heater]["properties"]["value"] is False
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_recipe_sliders_update_quickapp_variables() -> None:
    # a threshold slider in a recipe's UI: boot syncs it from the
    # quickAppVariable, a drag writes the variable back and the running
    # logic uses the new value on the very next poll
    engine = LuaEngine(speed=60.0)
    await engine.start()
    try:
        sensor, _ = engine.load_sim_device("humiditySensor", ["property:value=90"])
        fan, _ = engine.load_sim_device("binarySwitch")
        main = REPO / "recipes" / "humidity-fan" / "main.lua"
        qa_id, err = engine.load_qa_file(
            str(main), [f"var:humidityId={sensor}", f"var:fanId={fan}", "var:threshold=65"]
        )
        assert qa_id is not None and err is None, err
        await asyncio.sleep(0.7)  # the first 30s poll: 90 > 65 -> fan on
        assert engine.api.state.devices[fan]["properties"]["value"] is True
        # the slider shows the current threshold at boot
        layout, status = engine.api.dispatch("GET", f"/plugins/getView?id={qa_id}")
        assert status == 200
        assert "65" in json.dumps(layout)
        # drag the slider the way the viewer does
        engine.api.dispatch(
            "GET",
            f"/plugins/callUIEvent?deviceID={qa_id}&elementName=thresholdSlider"
            "&eventType=onChanged&value=95",
        )
        await asyncio.sleep(0.7)  # next poll: 90 <= 95 - 5 -> fan off
        assert engine.api.state.devices[fan]["properties"]["value"] is False
        # the variable persisted and the slider reflects it
        dev = engine.api.state.devices[qa_id]
        variables = {v["name"]: v["value"] for v in dev["properties"]["quickAppVariables"]}
        assert variables["threshold"] == 95
        layout, status = engine.api.dispatch("GET", f"/plugins/getView?id={qa_id}")
        assert status == 200
        assert "95" in json.dumps(layout)
    finally:
        await engine.stop()
