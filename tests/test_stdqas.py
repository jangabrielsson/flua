"""The standard QA templates (quickapp-types skill): quality gates.

Every template must pass ``--check``, and every template whose device type is
in the sim's catalog must boot cleanly offline. The catalog-gap types are
real HC3 types that the device catalog export (``devices.json``) doesn't
cover yet — they run on a real HC3, but flua's sim has no skeleton for
them; the set is pinned here so the gap is visible and shrinks as the
catalog grows.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.check import check_source  # noqa: E402
from flua.config import parse_annotations  # noqa: E402
from flua.engine import LuaEngine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = (
    REPO
    / "src"
    / "flua"
    / "setup_templates"
    / "github"
    / "skills"
    / "quickapp-types"
    / "templates"
)

# Device types the sim's catalog lacks — real HC3 types, sim-gap only.
CATALOG_GAPS = {
    "com.fibaro.hvacSystemHeatCool",
    "com.fibaro.thermostat",
    "com.fibaro.thermostatCool",
    "com.fibaro.thermostatHeat",
    "com.fibaro.thermostatHeatCool",
    "com.fibaro.thermostatSetpoint",
    "com.fibaro.thermostatSetpointCool",
    "com.fibaro.thermostatSetpointHeat",
    "com.fibaro.thermostatSetpointHeatCool",
    "com.fibaro.waterLeakSensor",
    "com.fibaro.windowCovering",
}


def _type_of(source: str) -> str:
    match = re.search(r"--%%type:(\S+)", source)
    assert match, "template without a --%%type header"
    return match.group(1)


def test_packaged_templates_match_the_skill_dir() -> None:
    skill = REPO / ".github" / "skills" / "quickapp-types" / "templates"
    assert {p.name for p in TEMPLATES.glob("*.lua")} == {
        p.name for p in skill.glob("*.lua")
    }


def test_all_templates_pass_check() -> None:
    engine = LuaEngine()
    lua = engine.lua_runtime()
    for path in sorted(TEMPLATES.glob("*.lua")):
        findings = check_source(path.read_text(encoding="utf-8"), path.name, lua)
        errors = [f for f in findings if ": error:" in f]
        assert not errors, f"{path.name}: {errors}"


async def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_templates_boot_clean_or_are_catalog_gaps() -> None:
    engine = LuaEngine()
    await engine.start()
    booted, gapped = 0, 0
    try:
        for path in sorted(TEMPLATES.glob("*.lua")):
            source = path.read_text(encoding="utf-8")
            device_type = _type_of(source)
            config = parse_annotations(source)  # like the CLI: the type comes from the header
            if device_type in CATALOG_GAPS:
                # sim gap: the boot attempt must fail with exactly this error
                with pytest.raises(ValueError, match="unknown device type"):
                    engine.start_qa(str(path), None, config, str(path))
                gapped += 1
                continue
            engine.start_qa(str(path), None, config, str(path))
            await _wait_until(lambda: not engine.has_pending_work())
            booted += 1
    finally:
        await engine.stop()
    assert booted + gapped == len(list(TEMPLATES.glob("*.lua")))
    assert booted > 0 and gapped == len(CATALOG_GAPS)
