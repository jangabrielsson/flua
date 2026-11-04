"""``flua --tool parityCapture`` — capture REST shape fixtures from a real
HC3 for offline parity replay.

Read-only: every probe is a GET, nothing on the controller is created or
changed. Output: ``tests/hc3_parity/fixtures/<softVersion>/`` with
``meta.json`` (provenance) and ``shapes.json`` (status + normalized shape
per probe), plus a compact diff against the previous fixture.

Run it from a flua checkout whenever the controller's firmware changes;
the offline replay suite (``tests/hc3_parity/test_hc3_replay.py``) then
pins the sim against the captured shapes in CI without a controller.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from flua import __version__
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
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (out_dir / "shapes.json").write_text(
        json.dumps({"probes": entries}, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {out_dir}")

    previous = sorted(
        d for d in fixtures.iterdir() if d.is_dir() and d.name != fw
    )
    if previous:
        _diff_summary(previous[-1], entries)
    return 0
