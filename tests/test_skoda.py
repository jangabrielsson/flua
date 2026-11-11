"""The Skoda pair: control QA + MyŠkoda API mock, fully offline.

The mock (net.HTTPServer) serves the API subset the control QA uses; the
control QA's refresh and actions drive it, and both directions are pinned:
mock state -> device properties, actions -> mock request log + state.
"""

import asyncio
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "Skoda"


async def wait_for(capsys, needle: str, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    out = ""
    while needle not in out:
        if time.monotonic() > deadline:
            raise AssertionError(f"not seen: {needle!r}; output so far:\n{out}")
        out = capsys.readouterr().out
        await asyncio.sleep(0.01)
    return out


async def wait_property(
    engine: LuaEngine, qa_id: int, prop: str, wanted, timeout: float = 5.0
) -> None:
    """Wait for a device property — or a QuickApp variable of that name
    (the Skoda QA keeps state/climate/target in the quickAppVariables
    property; variable values are strings)."""
    deadline = time.monotonic() + timeout
    while True:
        device = engine.api.state.devices[qa_id]
        if prop in device["properties"]:
            current = device["properties"].get(prop)
        else:
            qvars = {
                v["name"]: v["value"]
                for v in device["properties"].get("quickAppVariables") or []
            }
            current = qvars.get(prop)
        if current == wanted:
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"{prop} never became {wanted!r}")
        await asyncio.sleep(0.02)


async def start_pair(capsys, control_vars=None):
    engine = LuaEngine()
    await engine.start()
    mock_id, err = engine.load_qa_file(str(EXAMPLES / "myskoda_mock.lua"))
    assert err is None, err
    out = await wait_for(capsys, "SKODA_MOCK listening on ")
    port = int(re.search(r"listening on (\d+)", out).group(1))
    vars_ = ['var:url="http://127.0.0.1:' + str(port) + '"', *(control_vars or [])]
    control_id, err = engine.load_qa_file(str(EXAMPLES / "myskoda.lua"), vars_)
    assert err is None, err
    await wait_for(capsys, "SKODA 71 READY_FOR_CHARGING")
    return engine, mock_id, control_id


@pytest.mark.asyncio
async def test_skoda_pair_runs_offline(capsys) -> None:
    # once-mode: the control QA refreshes once against the mock, lands the
    # car state in its device properties, prints, and exits
    engine = None
    try:
        engine, _mock_id, control_id = await start_pair(capsys, ['var:once="true"'])
        dev = engine.api.state.devices[control_id]
        assert dev["properties"]["value"] is False  # not charging
        assert dev["properties"]["batteryLevel"] == 71  # the battery interface
        qvars = {
            v["name"]: v["value"]
            for v in dev["properties"].get("quickAppVariables") or []
        }
        assert qvars["state"] == "READY_FOR_CHARGING"
        assert qvars["target"] == "80"
    finally:
        if engine is not None:
            await engine.stop()


@pytest.mark.asyncio
async def test_skoda_actions_drive_the_mock(capsys) -> None:
    # live mode: actions round-trip through the mock and back into the
    # device properties
    engine = None
    try:
        engine, _mock_id, control_id = await start_pair(capsys)
        vin = "TMBMOCK123456789"
        engine.api.dispatch("POST", f"/devices/{control_id}/action/startCharging", {"args": []})
        await wait_for(capsys, f"MOCK POST /api/v1/vehicles/{vin}/charging/start")
        await wait_property(engine, control_id, "value", True)

        engine.api.dispatch(
            "POST", f"/devices/{control_id}/action/setChargingLimit", {"args": ["90"]}
        )
        await wait_for(capsys, f"MOCK PUT /api/v1/vehicles/{vin}/charging/limit")
        await wait_property(engine, control_id, "target", "90")

        engine.api.dispatch("POST", f"/devices/{control_id}/action/startAC", {"args": []})
        await wait_for(capsys, f"MOCK POST /api/v1/vehicles/{vin}/air-conditioning/start")
        await wait_property(engine, control_id, "climate", "ON")

        engine.api.dispatch("POST", f"/devices/{control_id}/action/stopCharging", {"args": []})
        await wait_for(capsys, f"MOCK POST /api/v1/vehicles/{vin}/charging/stop")
        await wait_property(engine, control_id, "value", False)
    finally:
        if engine is not None:
            await engine.stop()
