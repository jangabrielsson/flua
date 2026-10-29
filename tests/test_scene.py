"""--%%scene:true — the HC3 Lua scene runner.

Boot parses the declarations (COND) only; actions never run at boot, like
the HC3. Manual execute (POST /scenes/{id}/execute or fibaro.scene) runs
the actions with sourceTrigger = {type="manual"}. The conditions evaluator
fires on device/global-variable/custom-event triggers, date triggers arm
virtual-clock timers, and duration defers the run until the tree still
holds. The scene answers GET /scenes.
"""

import asyncio
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine

SCENE_SOURCE = """--%%name:TestScene
--%%scene:true
COND = {
    operator = "any",
    conditions = {
        { type = "date", property = "cron", operator = "match",
          -- year-pinned so the boot-time date trigger never arms: an
          -- all-wildcards cron matches every minute, and a boot landing
          -- near a minute boundary fired the scene inside the test's
          -- assertion window (the CI flake)
          value = {"*", "*", "*", "*", "*", "2050"}, isTrigger = true },
    }
}
-- ===== SCENE ACTIONS =====
print("SCENE_RAN", _sceneId, sourceTrigger and sourceTrigger.type)
"""


async def wait_for_output(capsys, needle: str, timeout: float = 3.0) -> str:
    deadline = time.monotonic() + timeout
    seen = ""
    while needle not in seen:
        if time.monotonic() > deadline:
            raise AssertionError(f"not seen: {needle!r}; output so far:\n{seen}")
        seen += capsys.readouterr().out
        await asyncio.sleep(0.01)
    return seen


@pytest.mark.asyncio
async def test_scene_boots_without_running_and_execute_runs_actions(tmp_path, capsys) -> None:
    script = tmp_path / "scene.lua"
    script.write_text(SCENE_SOURCE)
    engine = LuaEngine()
    await engine.start()
    try:
        qa_id = engine.start_qa(
            str(script), None, {"scene": True, "name": "TestScene"}, str(script)
        )
        # boot: registered as a scene, actions NOT run
        scenes, status = engine.api.dispatch("GET", "/scenes")
        assert status == 200
        assert {"id": qa_id, "name": "TestScene", "running": False, "kind": "luaScene"} in scenes
        await asyncio.sleep(0.2)
        assert "SCENE_RAN" not in capsys.readouterr().out  # actions did not run at boot

        # manual execute: the actions run with sourceTrigger = user
        data, status = engine.api.dispatch("POST", f"/scenes/{qa_id}/execute", None)
        assert status == 202
        await wait_for_output(capsys, f"SCENE_RAN {qa_id} manual")
        scene = engine.api.state.scenes[qa_id]
        assert scene["running"] is True
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_fibaro_scene_execute_from_another_qa(tmp_path, capsys) -> None:
    script = tmp_path / "scene.lua"
    script.write_text(SCENE_SOURCE)
    caller = tmp_path / "caller.lua"
    engine = LuaEngine()
    await engine.start()
    try:
        scene_id = engine.start_qa(
            str(script), None, {"scene": True, "name": "TestScene"}, str(script)
        )
        caller.write_text(
            "--%%name:Caller\n"
            "function QuickApp:onInit()\n"
            f"  fibaro.scene('execute', {{ {scene_id} }})\n"
            "end\n"
        )
        engine.start_qa(str(caller), None, {}, str(caller))
        await wait_for_output(capsys, f"SCENE_RAN {scene_id} manual")
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_scene_without_marker_fails_at_boot(tmp_path, capsys) -> None:
    script = tmp_path / "badscene.lua"
    script.write_text("--%%name:Bad\n--%%scene:true\nCOND = {}\nprint('NEVER')\n")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(
            str(script), None, {"scene": True, "name": "Bad"}, str(script)
        )
        deadline = time.monotonic() + 3.0
        seen = ""
        while time.monotonic() < deadline:
            seen += capsys.readouterr().out
            if "SCENE ACTIONS" in seen:
                break
            await asyncio.sleep(0.01)
        assert "SCENE ACTIONS" in seen  # the boot error names the marker
        assert "NEVER" not in seen
    finally:
        await engine.stop()


SCENE_TPL = """--%%name:Scene
--%%scene:true
COND = %s
-- ===== SCENE ACTIONS =====
print("SCENE_RAN", _sceneId, sourceTrigger and sourceTrigger.type)
"""

SEED = {
    "devices": [
        {"id": 10, "name": "lamp", "type": "com.fibaro.binarySwitch",
         "properties": {"value": False}},
        {"id": 20, "name": "motion", "type": "com.fibaro.binarySensor",
         "properties": {"value": False}},
    ]
}


@pytest.mark.asyncio
async def test_device_trigger_runs_scene(tmp_path, capsys) -> None:
    # device trigger + filter: the scene runs only when BOTH hold
    script = tmp_path / "scene.lua"
    script.write_text(SCENE_TPL % """{
        operator = "all",
        conditions = {
            { type = "device", id = 10, property = "value",
              operator = "==", value = true, isTrigger = true },
            { type = "device", id = 20, property = "value", operator = "==", value = true },
        }
    }""")
    engine = LuaEngine(seed=SEED)
    await engine.start()
    try:
        scene_id = engine.start_qa(str(script), None, {"scene": True, "name": "Scene"}, str(script))
        await asyncio.sleep(0.2)  # the pump boots the scene asynchronously
        # the filter (device 20) is not a trigger: its change runs nothing
        engine.api.dispatch("PUT", "/devices/20", {"properties": {"value": True}})
        await asyncio.sleep(0.3)
        assert "SCENE_RAN" not in capsys.readouterr().out
        # the trigger (device 10) flips while the filter holds -> run
        engine.api.dispatch("PUT", "/devices/10", {"properties": {"value": True}})
        await wait_for_output(capsys, f"SCENE_RAN {scene_id} device")
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_global_variable_trigger(tmp_path, capsys) -> None:
    script = tmp_path / "scene.lua"
    script.write_text(SCENE_TPL % """{
        operator = "any",
        conditions = {
            { type = "global-variable", property = "HomeMode",
              operator = "==", value = "Away", isTrigger = true },
        }
    }""")
    caller = tmp_path / "caller.lua"
    caller.write_text(
        "--%%name:Caller\n"
        "function QuickApp:onInit()\n"
        "  api.post('/globalVariables', {name = 'HomeMode', value = ''})\n"
        "  fibaro.setGlobalVariable('HomeMode', 'Away')\n"
        "end\n"
    )
    engine = LuaEngine(seed=SEED)
    await engine.start()
    try:
        scene_id = engine.start_qa(str(script), None, {"scene": True, "name": "Scene"}, str(script))
        engine.start_qa(str(caller), None, {}, str(caller))
        await wait_for_output(capsys, f"SCENE_RAN {scene_id} global-variable")
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_device_trigger_with_duration(tmp_path, capsys) -> None:
    # duration: the scene fires only if the whole tree still holds after the
    # duration — a change that breaks the condition cancels the pending run
    script = tmp_path / "scene.lua"
    script.write_text(SCENE_TPL % """{
        operator = "any",
        conditions = {
            { type = "device", id = 10, property = "value", operator = "==",
              value = true, isTrigger = true, duration = 2 },
        }
    }""")
    engine = LuaEngine(seed=SEED)
    await engine.start()
    try:
        scene_id = engine.start_qa(str(script), None, {"scene": True, "name": "Scene"}, str(script))
        await asyncio.sleep(0.2)  # the pump boots the scene asynchronously
        engine.api.dispatch("PUT", "/devices/10", {"properties": {"value": True}})
        await asyncio.sleep(0.2)
        assert "SCENE_RAN" not in capsys.readouterr().out  # duration not elapsed
        await wait_for_output(capsys, f"SCENE_RAN {scene_id} device")  # ~2 virtual s later
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_cron_trigger_fires_on_the_grid(tmp_path, capsys) -> None:
    script = tmp_path / "scene.lua"
    script.write_text(SCENE_TPL % """{
        operator = "any",
        conditions = {
            { type = "date", property = "cron", operator = "match",
              value = {"1", "12", "*", "*", "*", "*"}, isTrigger = true },
        }
    }""")
    from flua.clock import parse_start_time
    engine = LuaEngine(seed=SEED, start=parse_start_time("2026/10/19 12:00:30"), speed=60)
    await engine.start()
    try:
        scene_id = engine.start_qa(str(script), None, {"scene": True, "name": "Scene"}, str(script))
        await wait_for_output(capsys, f"SCENE_RAN {scene_id} date", timeout=5.0)
    finally:
        await engine.stop()


def test_example_scenes_self_tests() -> None:
    # examples/scenes.lua is the living fixture: a scene loaded from an
    # inline string, triggered by a device flip and by a manual execute
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", "examples/scenes.lua"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for line in (
        "scene in /scenes", "device trigger ran the scene", "manual execute ran the scene"
    ):
        assert f"PASS: {line}" in result.stdout
    assert "failures: 0" in result.stdout


@pytest.mark.asyncio
async def test_date_trigger_evaluates_at_scheduled_fire_time(tmp_path, capsys) -> None:
    # a date timer that fires LATE must still test its cron against the
    # SCHEDULED fire instant: the pump can overshoot a deadline (high
    # --speed does it every tick), and evaluating against the late clock
    # would silently miss the scene's slot. The clock jump here simulates
    # exactly that overshoot, deterministically.
    engine = LuaEngine()
    await engine.start()
    try:
        # the next minute boundary, pinned as the cron's minute AND hour
        # (so the hour rollover cannot shift the match)
        now = int(engine.clock.time)
        boundary = now - now % 60 + 60
        t = time.localtime(boundary)
        minute, hour = str(t.tm_min), str(t.tm_hour)
        script = tmp_path / "scene.lua"
        script.write_text(
            "--%%name:TestScene\n"
            "--%%scene:true\n"
            "COND = {\n"
            "    operator = 'any',\n"
            "    conditions = {\n"
            "        { type = 'date', property = 'cron', operator = 'match',\n"
            f"          value = {{{minute!r}, {hour!r}, '*', '*', '*', '*'}},"
            " isTrigger = true },\n"
            "    }\n"
            "}\n"
            "-- ===== SCENE ACTIONS =====\n"
            'print("SCENE_RAN", _sceneId, sourceTrigger and sourceTrigger.type)\n'
        )
        qa_id = engine.start_qa(
            str(script), None, {"scene": True, "name": "TestScene"}, str(script)
        )
        await asyncio.sleep(0.3)  # the scene boots and arms its date timer
        assert "SCENE_RAN" not in capsys.readouterr().out
        # fire the timer 61 s late: the clock reads minute+1 at evaluation
        engine.clock.time = float(boundary + 61)
        await wait_for_output(capsys, f"SCENE_RAN {qa_id} date")
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_year_pinned_cron_scene_boots_fast(capsys) -> None:
    # the year-pinned cron idiom (a "never fire" date trigger) must not
    # scan the whole 366-day window on boot — that was ~1.7 s of os.date
    # calls per scene boot and pushed the execute tests past their wait
    # window under CI load (the 0.1.102 failure)
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "scene.lua"
        script.write_text(SCENE_SOURCE)
        engine = LuaEngine()
        await engine.start()
        try:
            scene_id = engine.start_qa(
                str(script), None, {"scene": True, "name": "TestScene"}, str(script)
            )
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                info = engine.qa_info(scene_id)
                if info and info.get("loaded"):
                    break
                await asyncio.sleep(0.02)
            assert engine.qa_info(scene_id).get("loaded"), "scene boot stalled"
        finally:
            await engine.stop()
