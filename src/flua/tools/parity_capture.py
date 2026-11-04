"""``flua --tool parityCapture`` — capture REST shape fixtures from a real
HC3 for offline parity replay.

Read-only by default: every probe is a GET, nothing on the controller is
created or changed. ``--mutations`` adds the Tier-2 sequences — controlled
create/update/delete cycles over ``flua-p-<uuid8>``-namespaced artifacts
(QA, customEvent, globalVariable) with LIFO teardown afterwards.

Output: ``tests/hc3_parity/fixtures/<softVersion>/`` with ``meta.json``
(provenance), ``shapes.json`` (status + normalized shape per probe), and
``mutations.json`` when requested, plus a compact diff against the
previous fixture.

Run it from a flua checkout whenever the controller's firmware changes;
the offline replay suite (``tests/hc3_parity/test_hc3_replay.py``) then
pins the sim against the captured shapes in CI without a controller.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

from flua import __version__
from flua.parity.mutations import (
    SEQUENCES,
    ArtifactTracker,
    LiveBackend,
    run_sequence,
)
from flua.parity.normalize import drift, shape
from flua.parity.probes import PROBES

from .common import hc3_engine

NAME = "parityCapture"
HELP = "capture REST shape fixtures from a real HC3 for offline parity replay"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fw", help="fixture dir name (default: the controller's softVersion)"
    )
    parser.add_argument(
        "--fixtures",
        help="fixtures dir (default: <repo>/tests/hc3_parity/fixtures)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="resolve and print the probes, write nothing"
    )
    parser.add_argument(
        "--mutations",
        action="store_true",
        help="also run the Tier-2 mutation sequences (flua-p-* artifacts, "
        "cleaned up LIFO afterwards)",
    )
    parser.add_argument("--verbose", action="store_true", help="print each probe result")


def _repo_root() -> Path | None:
    for parent in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def _fixtures_dir(args: argparse.Namespace) -> Path:
    if args.fixtures:
        return Path(args.fixtures)
    root = _repo_root()
    if root is None:
        raise SystemExit(
            "error: run parityCapture from a flua checkout or pass --fixtures"
        )
    return root / "tests" / "hc3_parity" / "fixtures"


def _diff_summary(previous: Path, entries: list[dict]) -> None:
    """Compact advisory diff of the new capture vs the previous fixture."""
    old = {e["pattern"]: e for e in json.loads((previous / "shapes.json").read_text())["probes"]}
    new = {e["pattern"]: e for e in entries}
    lines: list[str] = []
    for pattern in sorted(set(new) | set(old)):
        if pattern not in old:
            lines.append(f"  new probe:     {pattern}")
            continue
        if pattern not in new:
            lines.append(f"  gone probe:    {pattern}")
            continue
        if new[pattern]["status"] != old[pattern]["status"]:
            lines.append(
                f"  status:        {pattern} {old[pattern]['status']} -> {new[pattern]['status']}"
            )
        if new[pattern]["shape"] != old[pattern]["shape"]:
            problems, gaps = drift(old[pattern]["shape"], new[pattern]["shape"], pattern)
            lines.append(f"  shape drift:   {pattern} ({len(problems)} problems, {len(gaps)} gaps)")
            for problem in problems[:5]:
                lines.append(f"                 {problem}")
    if lines:
        print(f"\ndiff vs {previous.name} (the previous capture):")
        print("\n".join(lines))
    else:
        print(f"\ndiff vs {previous.name}: no changes")


def _fqa_builder(engine: Any):
    """Builds the minimal .fqa the HC3's POST /quickApp expects — the same
    construction the live suite's QA round trip uses (a temp main.lua with
    the directives, packaged by the engine)."""

    def build(prefix: str) -> str:
        directory = Path(mkdtemp(prefix="flua-parity-"))
        main = directory / "main.lua"
        main.write_text(
            f"--%%name:{prefix}-qa\n"
            "--%%type:com.fibaro.binarySwitch\n"
            "-- --------------- EOH ---------------\n"
            "function QuickApp:onInit() end\n",
            encoding="utf-8",
        )
        qa_id = engine._prepare_qa(str(main), None, {"name": f"{prefix}-qa"}, str(main))
        fqa = engine.qa_export(qa_id)
        if fqa is None:
            raise ValueError("cannot build the parity probe .fqa")
        return json.dumps(fqa)

    return build


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engine = hc3_engine(parser)
    if engine.hc3 is None:
        parser.error("online mode required (HC3 credentials from the environment chain)")
    client = engine.hc3

    info, status = client.request("GET", "/settings/info")
    if status // 100 != 2:
        print(f"error: GET /settings/info failed ({status}) — is this an HC3?")
        return 1
    if args.fw and info.get("softVersion") != args.fw:
        print(
            f"warning: --fw {args.fw} but the controller reports softVersion "
            f"{info.get('softVersion')!r}"
        )
    fw = args.fw or info.get("softVersion") or "unknown"

    entries: list[dict] = []
    skipped: list[dict] = []
    for probe in PROBES:
        live_path = probe.live(client)
        if live_path is None:
            skipped.append(
                {"pattern": probe.pattern, "reason": "nothing on the HC3 to point the probe at"}
            )
            continue
        data, status = client.request("GET", live_path)
        entry: dict = {
            "pattern": probe.pattern,
            "path": live_path,
            "status": status,
            "shape": None,
        }
        if 200 <= status < 300 and isinstance(data, (dict, list)):
            if probe.live_filter is not None:
                data = probe.live_filter(data)
            entry["shape"] = shape(data)
        entries.append(entry)
        if args.verbose:
            note = f"  # {probe.note}" if probe.note else ""
            print(f"{status} {live_path}{note}")

    print(f"{len(entries)} probes captured, {len(skipped)} skipped")
    for skip in skipped:
        print(f"  skipped {skip['pattern']}: {skip['reason']}")

    mutation_fixture: dict | None = None
    if args.mutations:
        prefix = f"flua-p-{uuid.uuid4().hex[:8]}"
        tracker = ArtifactTracker(prefix)
        backend = LiveBackend(client)
        sequences = []
        for sequence in SEQUENCES:
            records, bindings = run_sequence(
                backend, sequence, prefix, _fqa_builder(engine)
            )
            for record in records:
                if args.verbose:
                    print(f"{sequence.id}/{record['step']}: {record['status']} {record['path']}")
            if sequence.id == "qaLifecycle":
                tracker.add("device", bindings["create.id"])
            if sequence.id == "customEvents":
                tracker.add("customEvent", f"{prefix}-evt")
            if sequence.id == "globalVariables":
                tracker.add("globalVariable", f"{prefix}-gv")
            sequences.append({"id": sequence.id, "note": sequence.note, "results": records})
        deleted, failed = tracker.teardown(backend)
        print(f"cleanup: {len(deleted)} artifacts removed, {len(failed)} failures")
        for failure in failed:
            print(f"  cleanup failed: {failure}")
        mutation_fixture = {
            "prefix": prefix,
            "sequences": sequences,
            "cleanup": {"deleted": deleted, "failed": failed},
        }

    if args.dry_run:
        return 0

    fixtures = _fixtures_dir(args)
    out_dir = fixtures / fw
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "captured": datetime.now(UTC).isoformat(),
        "softVersion": info.get("softVersion"),
        "serial": info.get("serialNumber"),
        "fluaVersion": __version__,
        "probeCount": len(entries),
        "skipped": skipped,
    }
    if mutation_fixture is not None:
        meta["mutations"] = {
            "prefix": mutation_fixture["prefix"],
            "sequences": [seq["id"] for seq in mutation_fixture["sequences"]],
            "cleanupFailed": mutation_fixture["cleanup"]["failed"],
        }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (out_dir / "shapes.json").write_text(
        json.dumps({"probes": entries}, indent=2) + "\n", encoding="utf-8"
    )
    if mutation_fixture is not None:
        (out_dir / "mutations.json").write_text(
            json.dumps(mutation_fixture, indent=2) + "\n", encoding="utf-8"
        )
    print(f"wrote {out_dir}")

    previous = sorted(
        d for d in fixtures.iterdir() if d.is_dir() and d.name != fw
    )
    if previous:
        _diff_summary(previous[-1], entries)
    return 0
