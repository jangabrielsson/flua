"""The Skoda pair: control QA + MyŠkoda API mock, fully offline.

The mock (net.HTTPServer) serves the API subset the control QA uses; the
control QA's refresh and actions drive it, and both directions are pinned:
mock state -> device properties, actions -> mock request log + state.
"""

import asyncio
import re
import socket
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
        out += capsys.readouterr().out
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
    # the mock binds an EPHEMERAL port (tests run in parallel workers —
    # a fixed port would collide) and the control is pointed at it; the
    # fixed-port design is the QA's default, exercised by the embedded test
    engine = LuaEngine()
    await engine.start()
    mock_id, err = engine.load_qa_file(str(EXAMPLES / "myskoda_mock.lua"), ["var:port=0"])
    assert err is None, err
    out = await wait_for(capsys, "SKODA_MOCK listening on ")
    port = int(re.search(r"listening on (\d+)", out).group(1))
    vars_ = [
        'var:url="http://127.0.0.1:' + str(port) + '"',
        'var:vin="TMBMOCK123456789"',
        'var:key="test-key"',
        *(control_vars or []),
    ]
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
        await wait_property(engine, control_id, "state", "CHARGING")

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
        await wait_property(engine, control_id, "state", "READY_FOR_CHARGING")
    finally:
        if engine is not None:
            await engine.stop()


@pytest.mark.asyncio
async def test_skoda_embeds_the_mock_when_no_url_is_set(capsys) -> None:
    # the pip-user shape: myskoda.lua alone, no url configured — the QA
    # loads the bundled mock QA and tests against it. The mock port is
    # overridden to a fresh one (the fixed default is for users; a live
    # instance or a parallel worker may hold 18290).
    def free_port() -> int:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        return port

    engine = LuaEngine()
    await engine.start()
    try:
        port = free_port()
        control_id, err = engine.load_qa_file(
            str(EXAMPLES / "myskoda.lua"),
            ['var:once="true"', "var:mockPort=" + str(port)],
        )
        assert err is None, err
        out = await wait_for(capsys, "SKODA 71 READY_FOR_CHARGING")
        assert f"using the MySkoda mock on {port}" in out
        assert "MOCK GET /api/v1/vehicles/TMBMOCK123456789" in out
        dev = engine.api.state.devices[control_id]
        assert dev["properties"]["batteryLevel"] == 71
    finally:
        await engine.stop()


def _probe_mock(port: int, count: int):
    # blocking HTTP from a worker thread: the mock's handler runs on the
    # pump (the test's own thread), so the requests must not block it
    import http.client

    results = []
    for _ in range(count):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/v1/vehicles/TMBMOCK123456789")
        resp = conn.getresponse()
        resp.read()
        results.append(
            (
                resp.status,
                resp.getheader("RateLimit-Remaining"),
                resp.getheader("Retry-After"),
            )
        )
        conn.close()
    return results


@pytest.mark.asyncio
async def test_mock_enforces_the_real_rate_limit(capsys) -> None:
    # the real API allows 20 requests/hour per VIN (the bundled docs); the
    # mock emulates it, headers included: 20 requests pass, the 21st is a
    # 429 with Retry-After
    engine = LuaEngine()
    await engine.start()
    try:
        _mock_id, err = engine.load_qa_file(
            str(EXAMPLES / "myskoda_mock.lua"), ["var:port=0"]
        )
        assert err is None, err
        out = await wait_for(capsys, "SKODA_MOCK listening on ")
        port = int(re.search(r"listening on (\d+)", out).group(1))
        results = await asyncio.to_thread(_probe_mock, port, 21)
        assert [r[0] for r in results[:20]] == [200] * 20
        assert results[19][1] == "0"  # the last allowed request
        assert results[20][0] == 429
        assert results[20][2] is not None  # Retry-After
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_mock_charges_to_target_at_the_charge_rate(capsys) -> None:
    # CHARGING advances the battery at chargeRate percent per VIRTUAL hour;
    # a high chargeRate plus the virtual clock fast-forwards the simulation
    engine = LuaEngine()
    await engine.start()
    try:
        _mock_id, err = engine.load_qa_file(
            str(EXAMPLES / "myskoda_mock.lua"),
            ["var:port=0", "var:chargeRate=3600"],  # 1% per virtual second
        )
        assert err is None, err
        out = await wait_for(capsys, "SKODA_MOCK listening on ")
        port = int(re.search(r"listening on (\d+)", out).group(1))
        control_id, err = engine.load_qa_file(
            str(EXAMPLES / "myskoda.lua"),
            [
                'var:url="http://127.0.0.1:' + str(port) + '"',
                'var:vin="TMBMOCK123456789"',
                'var:key="test-key"',
            ],
        )
        assert err is None, err
        await wait_for(capsys, "SKODA 71 READY_FOR_CHARGING")
        engine.api.dispatch(
            "POST", f"/devices/{control_id}/action/startCharging", {"args": []}
        )
        await wait_for(capsys, "MOCK POST /api/v1/vehicles/TMBMOCK123456789/charging/start")
        # 9 virtual seconds at 1%/s: 71% reaches the 80% target and the
        # mock flips back to READY_FOR_CHARGING on its own
        engine.clock.time = float(engine.clock.time + 9)
        engine.api.dispatch("POST", f"/devices/{control_id}/action/refresh", {"args": []})
        await wait_property(engine, control_id, "batteryLevel", 80)
        await wait_property(engine, control_id, "state", "READY_FOR_CHARGING")
    finally:
        await engine.stop()
