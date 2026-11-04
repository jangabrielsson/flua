"""Offline parity replay: captured HC3 fixtures vs the sim, no controller.

Run ``flua --tool parityCapture`` against a real HC3 first — the fixtures
land in ``tests/hc3_parity/fixtures/<softVersion>/``. This suite then
replays every captured GET against the offline sim and fails on *problems*
(status drift, offline-only fields, type mismatches — real compat bugs)
while reporting *gaps* (fields the HC3 has and the sim does not model).

``--parity-fw 5.221`` pins one fixture dir; the default is the newest.
Without any fixture the replay skips itself; the comparison machinery is
still pinned by the synthetic-transcript test below, and the probe table
coverage is pinned by ``test_every_get_route_is_probed``.
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.api import Api
from flua.parity.normalize import drift, shape
from flua.parity.probes import PROBES, PROBES_BY_PATTERN, route_coverage

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"


def _sim_api() -> Api:
    api = Api(seed=json.loads((REPO_ROOT / "examples/house.json").read_text()))
    api.register_qa(5000, "compat-qa", None, {})
    return api


def _fixture_dirs() -> list[Path]:
    if not FIXTURES.exists():
        return []
    return sorted(d for d in FIXTURES.iterdir() if d.is_dir())


def _load(fixture_dir: Path) -> tuple[dict, list[dict]]:
    meta = json.loads((fixture_dir / "meta.json").read_text())
    entries = json.loads((fixture_dir / "shapes.json").read_text())["probes"]
    return meta, entries


def _compare_entry(api: Api, entry: dict) -> tuple[list[str], list[str]]:
    """(problems, gaps) — replay one captured probe against the sim."""
    pattern = entry["pattern"]
    probe = PROBES_BY_PATTERN.get(pattern)
    if probe is None:
        return [f"{pattern}: no probe in the current table (route removed?)"], []
    data, status = api.dispatch("GET", probe.sim_path)
    problems: list[str] = []
    if status != entry["status"]:
        return [f"{pattern}: status {status} != captured {entry['status']}"], []
    if entry["shape"] is not None and 200 <= status < 300:
        problems, gaps = drift(shape(data), entry["shape"], pattern)
        return problems, gaps
    return problems, []


def _cases(config: pytest.Config) -> list[tuple[str, dict]]:
    dirs = _fixture_dirs()
    fw = config.getoption("--parity-fw")
    if fw:
        dirs = [d for d in dirs if d.name == fw]
    if not dirs:
        return []
    dirs = [dirs[-1]]  # newest by default
    cases: list[tuple[str, dict]] = []
    for fixture_dir in dirs:
        _meta, entries = _load(fixture_dir)
        for entry in entries:
            cases.append((fixture_dir.name, entry))
    return cases


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "case" in metafunc.fixturenames:
        cases = _cases(metafunc.config)
        if cases:
            metafunc.parametrize(
                "case", cases, ids=[f"{name}/{entry['pattern']}" for name, entry in cases]
            )


@pytest.mark.skipif(
    not _fixture_dirs(),
    reason="no captured fixtures — run flua --tool parityCapture against a real HC3",
)
def test_replay(case: tuple[str, dict]) -> None:
    _name, entry = case
    problems, gaps = _compare_entry(_sim_api(), entry)
    detail = "\n".join(problems)
    assert not problems, f"{entry['pattern']}: parity drift vs the captured HC3 fixture:\n{detail}"
    if gaps:
        print(
            f"info: {entry['pattern']} — {len(gaps)} fields the sim does not model: "
            + ", ".join(gaps[:5])
            + ("…" if len(gaps) > 5 else "")
        )


def test_replay_machinery_reports_drift() -> None:
    """The comparison logic, pinned without a controller: a synthetic
    transcript (hand-written, not HC3-captured) must flag status drift and
    type mismatches as problems and let unmodeled fields pass as gaps."""
    api = _sim_api()
    data, status = api.dispatch("GET", "/devices")
    assert status == 200

    good = {"pattern": "/devices", "status": 200, "shape": shape(data), "path": "/devices"}
    problems, gaps = _compare_entry(api, good)
    assert problems == [] and gaps == []

    # a live-side shape with an unmodeled field (gap) and a type mismatch
    # (problem) on the first device. The mismatch must be a real JSON type
    # change: shape() erases values, so the string "str" and the number 1
    # both become "str" — mutate to a bool, whose marker differs.
    device_shape = shape(data)[0]
    drifted = {"pattern": "/devices", "status": 200, "path": "/devices"}
    drifted["shape"] = [{**device_shape, "id": False, "batteryLevel": "number"}]
    problems, gaps = _compare_entry(api, drifted)
    assert any(".id:" in problem for problem in problems), problems
    assert any("batteryLevel" in gap for gap in gaps), gaps

    # status drift is a problem even when the shapes would agree
    status_drifted = {"pattern": "/devices", "status": 404, "shape": None, "path": "/devices"}
    problems, _gaps = _compare_entry(api, status_drifted)
    assert any("status" in problem for problem in problems), problems


def test_every_get_route_is_probed() -> None:
    """The route registry is the source of truth: every implemented GET is
    either a probe or a documented flua-only exclusion. A placeholder route
    without probe config is a bug — the harness would silently compare
    nothing."""
    coverage = route_coverage()
    assert coverage["uncovered"] == [], (
        "GET routes outside the probe table: " + ", ".join(coverage["uncovered"])
    )
    assert coverage["unconfigured"] == [], (
        "placeholder GET routes without probe config: "
        + ", ".join(coverage["unconfigured"])
    )
    assert len(PROBES) == len(coverage["probed"])
    for probe in PROBES:
        assert probe.pattern.startswith("/")
        assert "{" not in probe.sim_path, f"{probe.pattern}: sim_path has placeholders"
