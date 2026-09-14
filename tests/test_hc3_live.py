"""Live tests against a REAL HC3 — opt-in, production-aware.

Run explicitly with::

    HC3_TEST=1 pytest tests/test_hc3_live.py -v

Credentials come from the environment chain (.env): HC3_URL (or HC3_HOST),
HC3_USER, HC3_PASSWORD, HC3_PIN. The suite is deliberately careful:

- read-only tests only (settings, devices, globalVariables, refreshStates);
- the only mutations are importing a test QA and deleting it afterwards
  (never any existing device/globalVariable is touched);
- the auth-lockout guard applies: wrong credentials cost exactly one
  attempt, then flua aborts.

Skipped entirely unless HC3_TEST=1 AND HC3_URL/HC3_HOST are configured, so a
plain ``pytest`` run never reaches a production controller.
"""

import base64
import json
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.environment import EnvChain
from flua.engine import LuaEngine
from flua.hc3 import Hc3Remote

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    os.environ.get("HC3_TEST") != "1",
    reason="live HC3 tests: set HC3_TEST=1 and configure HC3 credentials in the environment",
)


def _client() -> Hc3Remote:
    env = EnvChain()
    base = env.get("HC3_URL") or f"http://{env.get('HC3_HOST')}/"
    if not base.strip("/"):
        pytest.skip("HC3_URL/HC3_HOST not configured in the environment")
    return Hc3Remote(
        base,
        user=env.get("HC3_USER"),
        password=env.get("HC3_PASSWORD"),
        pin=env.get("HC3_PIN"),
    )


def _wait_for(predicate, timeout: float, what: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(1.0)
    raise AssertionError(f"{what}: not observed within {timeout}s")


def _debug_text(client: Hc3Remote) -> str:
    data, _status = client.request("GET", "/debugMessages")
    return json.dumps(data or [])


def _test_fqa(tmp_path: Path, name: str) -> dict:
    """Build a valid .fqa for a QA that announces itself and echoes calls."""
    main = tmp_path / "main.lua"
    main.write_text(
        f"--%%name:{name}\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  print('flua-live-test started')\n"
        "end\n"
        "function QuickApp:echo(v)\n"
        "  print('ECHO ' .. tostring(v))\n"
        "end\n"
        "function QuickApp:toggle()\n"
        "  self:updateProperty('value', not (self:getProperty('value') or false))\n"
        "  print('TOGGLED')\n"
        "end\n"
    )
    engine = LuaEngine()
    qa_id = engine._prepare_qa(str(main), None, {"name": name}, str(main))
    return engine.qa_export(qa_id)


# -- read-only ------------------------------------------------------------------


def test_settings_info_is_readable() -> None:
    client = _client()
    data, status = client.request("GET", "/settings/info")
    assert status == 200
    assert data["serialNumber"]
    assert data["softVersion"]


def test_devices_are_listed() -> None:
    client = _client()
    devices, status = client.request("GET", "/devices")
    assert status == 200
    assert isinstance(devices, list)
    for device in devices:
        assert isinstance(device.get("id"), int)
        assert device.get("name")


def test_global_variables_are_listed() -> None:
    client = _client()
    variables, status = client.request("GET", "/globalVariables")
    assert status == 200
    assert isinstance(variables, list)


def test_refresh_states_shape() -> None:
    client = _client()
    data, status = client.request("GET", "/refreshStates")
    assert status == 200
    # the idle base shape; changes/events appear only with pending activity
    for key in ("status", "last", "date", "timestamp", "timestampMillis"):
        assert key in data
    assert isinstance(data["last"], int)


# -- QA upload lifecycle --------------------------------------------------------


def test_import_invalid_fqa_is_rejected_without_harm(tmp_path: Path) -> None:
    client = _client()
    before, _ = client.request("GET", "/devices")
    before_ids = {d["id"] for d in before}

    # semantically invalid (valid JSON, no main file) — plua's transport:
    # POST /quickApp/ with the raw fqa string as the body
    garbage = json.dumps({"files": []})
    _data, status = client.request("POST", "/quickApp/", body=garbage)
    assert status in (400, 415, 422, 500)  # the HC3 rejects; any non-2xx is fine

    after, _ = client.request("GET", "/devices")
    after_ids = {d["id"] for d in after}
    assert before_ids == after_ids  # nothing was created


def test_import_call_and_delete(tmp_path: Path) -> None:
    client = _client()
    name = f"flua-live-{int(time.time())}"
    fqa = _test_fqa(tmp_path, name)
    payload = json.dumps(fqa)  # the raw .fqa JSON string, like plua's uploadFQA

    # the HC3's import can be slow to recover between attempts — retry with
    # backoff instead of hammering a production controller
    device = last_error = None
    for _attempt in range(3):
        device, status = client.request("POST", "/quickApp/", body=payload)
        if status in (200, 201):
            break
        last_error = device
        time.sleep(20)
    assert status in (200, 201), last_error
    device_id = device["id"] if isinstance(device, dict) and "id" in device else int(device)
    try:
        # the QA boots and announces itself in the debug log
        _wait_for(
            lambda: "flua-live-test started" in _debug_text(client),
            timeout=60,
            what="imported QA startup",
        )
        # fibaro.call reaches the uploaded QA's method
        result, status = client.request(
            "POST", f"/devices/{device_id}/action/echo", body={"args": [42]}
        )
        assert status == 202, (status, result)
        _wait_for(
            lambda: "ECHO 42" in _debug_text(client),
            timeout=30,
            what="echo action",
        )
        # activity on OUR device shows up in the refreshStates EVENTS feed
        # (the interesting one — changes is mostly UI noise). Capture `last`
        # before the action and look for our device id afterwards; print the
        # observed entry so the real HC3's shape is visible.
        before, _ = client.request("GET", "/refreshStates")
        last = before["last"]
        client.request("POST", f"/devices/{device_id}/action/toggle", body={"args": []})

        def _event_seen() -> bool:
            data, status = client.request("GET", "/refreshStates", {"last": last})
            if status != 200:
                return False
            entries = (data.get("events") or []) + (data.get("changes") or [])
            for entry in entries:
                if str(device_id) in json.dumps(entry):
                    print("observed refreshStates event:", json.dumps(entry, indent=1))
                    return True
            if entries:
                print("refreshStates entries so far (no match):", json.dumps(entries, indent=1))
            return False

        _wait_for(_event_seen, timeout=30, what="refreshStates event for the test QA")
    finally:
        # clean up the production controller: remove only OUR test QA
        client.request("DELETE", f"/devices/{device_id}")