"""Tier-2 mutation machinery, pinned offline against the sim.

Round-trip tests: run a sequence on one sim, replay the recorded results
on a fresh sim, and require agreement — the same comparison the fixture
replay makes, exercised without a controller. Plus the artifact tracker's
LIFO teardown, template-error handling, and the parityCleanup scan/delete
logic (stub client, no controller).
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.api import Api
from flua.engine import LuaEngine
from flua.parity.mutations import (
    SEQUENCES_BY_ID,
    ArtifactTracker,
    Sequence,
    SimBackend,
    Step,
    run_sequence,
)
from flua.tools.parity_cleanup import check_prefix, delete_artifacts, scan_artifacts

REPO_ROOT = Path(__file__).resolve().parents[2]
PREFIX = "flua_p_test00"


def _state_api() -> Api:
    return Api(seed=json.loads((REPO_ROOT / "examples/house.json").read_text()))


def test_events_and_globals_round_trip() -> None:
    for sequence_id in ("customEvents", "globalVariables"):
        sequence = SEQUENCES_BY_ID[sequence_id]
        first, _ = run_sequence(SimBackend(_state_api()), sequence, PREFIX)
        second, _ = run_sequence(SimBackend(_state_api()), sequence, PREFIX)
        assert [r["status"] for r in first] == [r["status"] for r in second]
        assert [r["shape"] for r in first] == [r["shape"] for r in second]


def test_global_variable_statuses_are_pinned() -> None:
    """The sim's response statuses for the add/change/read/delete cycle —
    the HC3-verified baseline (live 5.221): create 201, delete 200
    (idempotent), post-delete read 404."""
    records, _ = run_sequence(SimBackend(_state_api()), SEQUENCES_BY_ID["globalVariables"], PREFIX)
    assert [r["status"] for r in records] == [201, 200, 200, 200, 404]
    assert [r["shape"] for r in records][0] is not None  # the create response has a shape
    assert records[-1]["shape"] is None  # the post-delete read has no 2xx body


def test_custom_event_statuses_are_pinned() -> None:
    """The sim's customEvents cycle — HC3-verified (live 5.221): create
    201, fire/publish/delete 204 (also on absent names)."""
    records, _ = run_sequence(SimBackend(_state_api()), SEQUENCES_BY_ID["customEvents"], PREFIX)
    assert [r["status"] for r in records] == [201, 200, 204, 204, 204]


def test_qa_lifecycle_on_the_sim() -> None:
    engine = LuaEngine()
    records, bindings = run_sequence(
        SimBackend(engine.api), SEQUENCES_BY_ID["qaLifecycle"], PREFIX
    )
    assert [r["status"] for r in records] == [201, 200, 400, 200, 200]
    # updateProperty from an external caller is 400 (the HC3's answer,
    # live-verified) — the sim mirrors it since the first capture
    qa_id = bindings["create.id"]
    assert qa_id  # the create response's id was extracted into the templates
    # the templated paths really used the extracted id
    assert records[1]["path"] == f"/plugins/{qa_id}"
    assert records[2]["path"] == "/plugins/updateProperty"
    assert records[3]["path"] == f"/devices/{qa_id}/properties/userDescription"
    assert records[4]["path"] == f"/devices/{qa_id}"
    # the delete worked: the QA is gone
    _data, status = engine.api.dispatch("GET", f"/devices/{qa_id}")
    assert status == 404


class _RecordingBackend:
    is_sim = True

    def __init__(self, status: int = 204) -> None:
        self.calls: list[tuple[str, str]] = []
        self._status = status

    def call(self, method: str, path: str, body: object = None) -> tuple[None, int]:
        self.calls.append((method, path))
        return None, self._status


def test_artifact_tracker_teardown_is_lifo() -> None:
    backend = _RecordingBackend()
    tracker = ArtifactTracker(PREFIX)
    tracker.add("device", 5001)
    tracker.add("customEvent", f"{PREFIX}_evt")
    tracker.add("globalVariable", f"{PREFIX}_gv")
    deleted, failed = tracker.teardown(backend)
    assert [path for _method, path in backend.calls] == [
        f"/globalVariables/{PREFIX}_gv",
        f"/customEvents/{PREFIX}_evt",
        "/devices/5001",
    ]
    assert len(deleted) == 3 and failed == []


def test_artifact_tracker_counts_404_as_gone() -> None:
    backend = _RecordingBackend(status=404)
    tracker = ArtifactTracker(PREFIX)
    tracker.add("device", 5001)
    deleted, failed = tracker.teardown(backend)
    assert deleted == ["device 5001"] and failed == []


def test_unresolved_template_raises() -> None:
    sequence = Sequence("t", "", [Step("s", "GET", "/x/{nope}")])
    with pytest.raises(ValueError, match="unresolved template"):
        run_sequence(SimBackend(_state_api()), sequence, PREFIX)


class _StubClient:
    def __init__(self, devices: list, globals_: list, events: list) -> None:
        self._data = {
            "/devices": devices,
            "/globalVariables": globals_,
            "/customEvents": events,
        }
        self.deletes: list[str] = []

    def request(self, method: str, path: str, **kwargs: object) -> tuple[object, int]:
        if method == "DELETE":
            self.deletes.append(path)
            return None, 204
        return self._data.get(path, []), 200


def test_cleanup_scan_groups_by_prefix() -> None:
    client = _StubClient(
        devices=[
            {"id": 1, "name": "Ceiling Lamp"},
            {"id": 5001, "name": f"{PREFIX}_qa"},
            {"id": 5002, "name": "flua_p_other_qv"},
        ],
        globals_=[{"name": "nightMode"}, {"name": f"{PREFIX}_gv"}],
        events=[{"name": f"{PREFIX}_evt"}, {"name": "userEvent"}],
    )
    found = scan_artifacts(client, PREFIX)
    assert [d["id"] for d in found["devices"]] == [5001]  # the other prefix is excluded
    assert [g["name"] for g in found["globalVariables"]] == [f"{PREFIX}_gv"]
    assert [e["name"] for e in found["customEvents"]] == [f"{PREFIX}_evt"]

    delete_artifacts(client, found)
    assert client.deletes == [
        "/devices/5001",
        f"/globalVariables/{PREFIX}_gv",
        f"/customEvents/{PREFIX}_evt",
    ]


def test_cleanup_prefix_guard() -> None:
    assert check_prefix("flua_p_") == "flua_p_"
    assert check_prefix("flua_p_abcd") == "flua_p_abcd"
    with pytest.raises(ValueError, match="must start with 'flua_p_'"):
        check_prefix("devices")
    with pytest.raises(ValueError, match="must start with 'flua_p_'"):
        check_prefix("")
