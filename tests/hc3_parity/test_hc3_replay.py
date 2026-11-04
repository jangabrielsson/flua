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

import asyncio
import json
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.api import Api
from flua.engine import LuaEngine
from flua.parity.fibaro_probes import FIBARO_PROBES
from flua.parity.mutations import SEQUENCES_BY_ID, SimBackend, run_sequence
from flua.parity.normalize import drift, shape
from flua.parity.probes import PROBES, PROBES_BY_PATTERN, route_coverage

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
PROBE_QA = Path(__file__).parent / "probe_qa" / "main.lua"


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


@pytest.mark.skipif(
    not _fixture_dirs(),
    reason="no captured fixtures — run flua --tool parityCapture --mutations against a real HC3",
)
def test_replay_mutations(request: pytest.FixtureRequest) -> None:
    """Replay the Tier-2 mutation sequences against the sim. Each fixture
    with a mutations.json runs the same create/update/delete cycles
    (namespaced flua-p-* artifacts, ephemeral sim) and compares status +
    shape per step — ids are re-bound from the sim's own responses."""
    dirs = _fixture_dirs()
    fw = request.config.getoption("--parity-fw")
    if fw:
        dirs = [d for d in dirs if d.name == fw]
    dirs = [d for d in dirs if (d / "mutations.json").exists()]
    if not dirs:
        pytest.skip("no captured mutations — capture with --mutations")
    fixture_dir = dirs[-1]
    fixture = json.loads((fixture_dir / "mutations.json").read_text())

    engine = LuaEngine(seed=json.loads((REPO_ROOT / "examples/house.json").read_text()))
    backend = SimBackend(engine.api)
    problems: list[str] = []
    gaps: list[str] = []
    for sequence_fixture in fixture["sequences"]:
        sequence = SEQUENCES_BY_ID.get(sequence_fixture["id"])
        if sequence is None:
            problems.append(f"{sequence_fixture['id']}: no such sequence in the current table")
            continue
        records, _bindings = run_sequence(backend, sequence, fixture["prefix"])
        if len(records) != len(sequence_fixture["results"]):
            problems.append(
                f"{sequence_fixture['id']}: sequence changed since capture "
                f"({len(records)} steps vs {len(sequence_fixture['results'])} recorded)"
            )
            continue
        for record, expected in zip(records, sequence_fixture["results"], strict=True):
            label = f"{sequence_fixture['id']}/{record['step']}"
            if record["status"] != expected["status"]:
                problems.append(
                    f"{label}: status {record['status']} != captured {expected['status']}"
                )
            elif record["shape"] is not None and expected["shape"] is not None:
                sub_problems, sub_gaps = drift(record["shape"], expected["shape"], label)
                problems += sub_problems
                gaps += sub_gaps
    assert not problems, "mutation parity drift vs the captured HC3 fixture:\n" + "\n".join(
        problems
    )
    if gaps:
        print("info: mutation gaps (fields the sim does not model): " + ", ".join(gaps[:10]))


async def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("not observed within timeout")


def _normalize_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sim_probe_transcript(engine: LuaEngine) -> list[str]:
    """The sim's transcript of the probe QA — the same tag filter and
    normalization the capture applies to the HC3's /debugMessages."""
    data, status = engine.api.dispatch("GET", "/debugMessages")
    assert status == 200
    return [
        _normalize_line(str(entry.get("message", "")))
        for entry in (data.get("messages") or [])
        if isinstance(entry, dict)
        and str(entry.get("tag", "")).startswith("flua-p-probe")
        and str(entry.get("message", "")).startswith("PROBE")
    ]


def _fibaro_qa_source(probes: list[tuple[str, list]]) -> str:
    """A QA that calls each fibaro.<name>(...) under pcall and prints one
    FIBARO line per probe: name, ok, and the return values as JSON."""
    lines = [
        "function QuickApp:onInit()",
        "  local function emit(name, fn)",
        "    local res = {pcall(fn)}",
        "    local vals = {select(2, table.unpack(res))}",
        '    print("FIBARO " .. name .. " " .. tostring(res[1]) .. " " .. json.encode(vals))',
        "  end",
    ]
    for name, args in probes:
        arg_lua = ", ".join(json.dumps(arg) for arg in args)
        lines.append(f'  emit("{name}", function() return fibaro.{name}({arg_lua}) end)')
    lines.append("end")
    return "\n".join(lines) + "\n"


def _parse_fibaro_lines(out: str) -> dict[str, tuple[bool, list]]:
    """Parse the QA's FIBARO lines. In text log mode every line carries the
    [timestamp][LEVEL][tag]: prefix, so match anywhere in the line."""
    results: dict[str, tuple[bool, list]] = {}
    for line in out.splitlines():
        match = re.search(r"FIBARO (\S+) (\S+) (.*)$", line)
        if match is None:
            continue
        name, ok_text, vals_text = match.groups()
        values = json.loads(vals_text)
        if isinstance(values, dict) and not values:
            values = []  # Lua's json encodes an empty array-valued table as {}
        results[name] = (ok_text == "true", values)
    return results


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


async def test_probe_qa_runs_in_the_sim(capsys: pytest.CaptureFixture) -> None:
    """The probe QA completes in the sim with a deterministic, sentinel-
    bounded transcript — the offline half of the Tier-3 comparison, pinned
    without a controller."""
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(PROBE_QA), None, {"name": "flua-p-probe"}, str(PROBE_QA))
        await _wait_until(lambda: not engine.has_pending_work())
        transcript = _sim_probe_transcript(engine)
        assert transcript, "the probe QA logged nothing"
        assert transcript[-1] == "PROBE timer fired"
        assert "PROBE_DONE" in transcript
        # deterministic: a second run produces the identical transcript
        second = LuaEngine()
        await second.start()
        try:
            second.start_qa(str(PROBE_QA), None, {"name": "flua-p-probe"}, str(PROBE_QA))
            await _wait_until(lambda: not second.has_pending_work())
            assert _sim_probe_transcript(second) == transcript
        finally:
            await second.stop()
    finally:
        await engine.stop()
    assert "no output" not in capsys.readouterr().out  # the run produced stdout


@pytest.mark.skipif(
    not _fixture_dirs(),
    reason="no captured fixtures — run flua --tool parityCapture --probe against a real HC3",
)
async def test_replay_probe_qa() -> None:
    """The captured HC3 transcript vs the sim's, line by line."""
    dirs = _fixture_dirs()
    dirs = [d for d in dirs if (d / "probe_qa.json").exists()]
    if not dirs:
        pytest.skip("no captured probe QA transcript — capture with --probe")
    fixture = json.loads((dirs[-1] / "probe_qa.json").read_text())

    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(PROBE_QA), None, {"name": "flua-p-probe"}, str(PROBE_QA))
        await _wait_until(lambda: not engine.has_pending_work())
        sim = _sim_probe_transcript(engine)
    finally:
        await engine.stop()

    captured = fixture["transcript"]
    assert sim == captured, (
        "probe QA transcript drift vs the captured HC3 fixture "
        f"({len(sim)} sim lines vs {len(captured)} captured):\n"
        + "\n".join(
            (
                "< sim"
                if i >= len(captured) or i >= len(sim) or sim[i] != captured[i]
                else "     "
            )
            + f" {sim[i] if i < len(sim) else '(missing)'} | "
            f"{captured[i] if i < len(captured) else '(missing)'}"
            for i in range(max(len(sim), len(captured)))
        )
    )


async def test_sim_fibaro_contract(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The sim's fibaro table under the probe conditions — the offline
    baseline. getName() requires a deviceId on the sim today (the HC3
    tolerates no args); the fixture replay surfaces that divergence when a
    capture exists."""
    main = tmp_path / "main.lua"
    main.write_text(
        _fibaro_qa_source([(name, args) for name, args, _note in FIBARO_PROBES]),
        encoding="utf-8",
    )
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(main), None, {}, str(main))
        await _wait_until(lambda: not engine.has_pending_work())
        out = capsys.readouterr().out
    finally:
        await engine.stop()

    results = _parse_fibaro_lines(out)
    assert set(results) == {name for name, _args, _note in FIBARO_PROBES}
    assert results["getName"][0] is False  # the sim's signature check
    ok, values = results["getGlobalVariable"]
    assert ok is True and values == []  # absent variable -> nil
    assert results["getSelfId"][0] is False  # not a sim function either
    assert results["nope"][0] is False


async def test_replay_fibaro(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The captured helperFibaro results vs the sim's fibaro table: ok/error
    contract and value types, per probe."""
    dirs = _fixture_dirs()
    dirs = [d for d in dirs if (d / "fibaro.json").exists()]
    if not dirs:
        pytest.skip("no captured fibaro probes — capture with --fibaro")
    fixture = json.loads((dirs[-1] / "fibaro.json").read_text())
    probes = [
        (entry["name"], entry["args"])
        for entry in fixture["probes"]
    ]
    main = tmp_path / "main.lua"
    main.write_text(_fibaro_qa_source(probes), encoding="utf-8")
    engine = LuaEngine()
    await engine.start()
    try:
        engine.start_qa(str(main), None, {}, str(main))
        await _wait_until(lambda: not engine.has_pending_work())
        out = capsys.readouterr().out
    finally:
        await engine.stop()

    sim = _parse_fibaro_lines(out)
    problems: list[str] = []
    for entry in fixture["probes"]:
        name = entry["name"]
        if name not in sim:
            problems.append(f"fibaro.{name}: the sim produced no result")
            continue
        ok, values = sim[name]
        if ok != entry["ok"]:
            problems.append(
                f"fibaro.{name}: sim ok={ok} != captured ok={entry['ok']} "
                f"(captured error: {entry.get('error')})"
            )
        elif entry["ok"] and shape(values) != entry["valuesShape"]:
            problems.append(
                f"fibaro.{name}: value shape {shape(values)!r} != "
                f"captured {entry['valuesShape']!r}"
            )
    assert not problems, "fibaro parity drift vs the captured HC3 fixture:\n" + "\n".join(
        problems
    )
