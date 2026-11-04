"""Compatibility oracle: the same REST call through the offline sim and the
real HC3 must agree on response shape (status code + JSON structure, not
concrete values). Every mismatch is either a sim bug or a documented gap.

Opt-in like the live suite::

    HC3_TEST=1 pytest tests/test_hc3_compat.py -v

Read-only endpoints only.
"""

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.api import Api
from flua.environment import EnvChain
from flua.hc3 import Hc3Remote
from flua.parity.normalize import drift

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    os.environ.get("HC3_TEST") != "1",
    reason="live HC3 tests: set HC3_TEST=1 and configure HC3 credentials in the environment",
)


def _live_client() -> Hc3Remote:
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


def _offline_api() -> Api:
    api = Api(seed=json.loads(Path(REPO_ROOT / "examples/house.json").read_text()))
    # a catalog-skeleton QA device: the same shape a real HC3 device has
    api.register_qa(5000, "compat-qa", None, {})
    return api


def _compare(method: str, path: str, live_filter=None) -> None:
    live = _live_client()
    live_data, live_status = live.request(method, path)
    assert live_status == 200, f"live {method} {path} failed: {live_status}"
    if live_filter is not None:
        live_data = live_filter(live_data)

    offline = _offline_api()
    offline_data, offline_status = offline.dispatch(method, path)
    assert offline_status == 200, f"offline {method} {path} failed: {offline_status}"

    problems, gaps = drift(offline_data, live_data)
    assert not problems, f"{method} {path} shape drift vs the real HC3:\n" + "\n".join(problems)
    if gaps:
        print(
            f"info: {method} {path} — {len(gaps)} fields the sim does not model yet "
            f"(catalog-capture gaps): " + ", ".join(gaps[:5]) + ("…" if len(gaps) > 5 else "")
        )


@pytest.mark.parametrize(
    "method,path,live_filter",
    [
        (
            "GET",
            "/devices",
            lambda devices: [d for d in devices if d.get("type") == "com.fibaro.binarySwitch"],
        ),
        ("GET", "/globalVariables", None),
        ("GET", "/rooms", None),
        ("GET", "/refreshStates", None),
    ],
)
def test_shape_matches_real_hc3(method: str, path: str, live_filter) -> None:
    _compare(method, path, live_filter)


def test_single_device_shape_matches() -> None:
    # offline: the catalog-skeleton QA device (a real HC3 capture);
    # live: the first real device. Shapes should agree.
    live = _live_client()
    devices, status = live.request("GET", "/devices?type=com.fibaro.binarySwitch")
    assert status == 200 and devices, "no binarySwitch devices on the HC3"
    live_device, live_status = live.request("GET", f"/devices/{devices[0]['id']}")
    assert live_status == 200

    offline = _offline_api()
    offline_device, offline_status = offline.dispatch("GET", "/devices/5000")
    assert offline_status == 200

    problems, gaps = drift(offline_device, live_device)
    assert not problems, "device shape drift vs the real HC3:\n" + "\n".join(problems)
    if gaps:
        print(
            f"info: single-device — {len(gaps)} fields the sim does not model yet "
            f"(catalog-capture gaps): " + ", ".join(gaps[:5]) + ("…" if len(gaps) > 5 else "")
        )
