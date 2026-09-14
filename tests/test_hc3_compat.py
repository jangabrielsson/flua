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


def _shape(value) -> object:
    """JSON structure, ignoring concrete values: field names + types."""
    if isinstance(value, dict):
        return {key: _shape(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return "str"


def _drift(offline: object, live: object, path: str = "") -> tuple[list[str], list[str]]:
    """(problems, gaps) between two JSON structures. Problems are offline-only
    fields and type mismatches on common fields — real compat bugs. Gaps are
    fields the live HC3 has and the sim lacks — the sim is an incomplete
    subset (catalog-capture limits), reported but not failed."""
    problems: list[str] = []
    gaps: list[str] = []
    if isinstance(live, dict):
        if not isinstance(offline, dict):
            problems.append(f"{path or '/'}: offline={type(offline).__name__}, live=object")
            return problems, gaps
        for key in sorted(set(live) - set(offline)):
            gaps.append(f"{path}.{key}: missing offline (live has {_shape(live[key])!r})")
        for key in sorted(set(offline) - set(live)):
            problems.append(f"{path}.{key}: only offline (live lacks it)")
        for key in sorted(set(live) & set(offline)):
            sub_problems, sub_gaps = _drift(offline[key], live[key], f"{path}.{key}")
            problems += sub_problems
            gaps += sub_gaps
    elif isinstance(live, list):
        if not isinstance(offline, list):
            problems.append(f"{path or '/'}: offline={type(offline).__name__}, live=list")
        elif live and offline:
            sub_problems, sub_gaps = _drift(offline[0], live[0], f"{path}[]")
            problems += sub_problems
            gaps += sub_gaps
    else:
        expected = _shape(live)
        actual = _shape(offline)
        if actual != expected:
            problems.append(f"{path or '/'}: offline={actual!r}, live={expected!r}")
    return problems, gaps


def _compare(method: str, path: str, live_filter=None) -> None:
    live = _live_client()
    live_data, live_status = live.request(method, path)
    assert live_status == 200, f"live {method} {path} failed: {live_status}"
    if live_filter is not None:
        live_data = live_filter(live_data)

    offline = _offline_api()
    offline_data, offline_status = offline.dispatch(method, path)
    assert offline_status == 200, f"offline {method} {path} failed: {offline_status}"

    problems, gaps = _drift(offline_data, live_data)
    assert not problems, f"{method} {path} shape drift vs the real HC3:\n" + "\n".join(problems)
    if gaps:
        print(f"info: {method} {path} — {len(gaps)} fields the sim does not model yet "
              f"(catalog-capture gaps): " + ", ".join(gaps[:5]) + ("…" if len(gaps) > 5 else ""))


@pytest.mark.parametrize(
    "method,path,live_filter",
    [
        ("GET", "/devices", lambda devices: [d for d in devices if d.get("type") == "com.fibaro.binarySwitch"]),
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

    problems, gaps = _drift(offline_device, live_device)
    assert not problems, "device shape drift vs the real HC3:\n" + "\n".join(problems)
    if gaps:
        print(f"info: single-device — {len(gaps)} fields the sim does not model yet "
              f"(catalog-capture gaps): " + ", ".join(gaps[:5]) + ("…" if len(gaps) > 5 else ""))