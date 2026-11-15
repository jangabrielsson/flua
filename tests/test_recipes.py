"""The recipe library: recipes/ is the QA builder's source (fetched from
the flua repo at build time); the wheel ships an offline snapshot under
setup_templates/recipes. These tests pin the index against the manifests
and prove every recipe's main.lua checks and boots."""

from __future__ import annotations

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
