"""test: run a project's test_*.lua suite — the flua-test verify loop.

The CI shape the field reports keep hand-rolling: discover ``test_*.lua``,
run each in the offline sim (``--instant`` for virtual-time speed), print
one summary line, exit nonzero when anything failed. Pair with
``--deadline SEC`` so a hung test is a failed run, not a job timeout.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

NAME = "test"
HELP = "run a project's test_*.lua suite — one summary, nonzero exit (agents: --json)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dir",
        action="append",
        default=[],
        metavar="DIR",
        help="discover test_*.lua under this directory (repeatable; default .)",
    )
    parser.add_argument(
        "--instant",
        action="store_true",
        help="run the tests on the instant virtual clock (hours of sim time at CPU speed)",
    )
    parser.add_argument(
        "--api",
        choices=("local", "remote"),
        default="local",
        help="the engine's API mode (default local — sim HC3, real network)",
    )
    parser.add_argument(
        "--deadline",
        type=float,
        metavar="SEC",
        help="wall-clock cap per test, enforced by the runner: a finished test "
        "ends instantly, a hung one is killed and counted as failed",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable results (agents)")


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    roots = [Path(entry) for entry in (args.dir or ["."])]
    files: list[Path] = []
    for root in roots:
        files.extend(sorted(root.rglob("test_*.lua")))
    if not files:
        print(f"test: no test_*.lua under {', '.join(str(r) for r in roots)}", file=sys.stderr)
        return 1
    results: list[dict[str, object]] = []
    for path in files:
        command = [sys.executable, "-m", "flua", "--api", args.api]
        if args.instant:
            command.append("--instant")
        command.append(str(path))
        if args.deadline is not None:
            # the runner's own wall clock — NOT --run-for, whose "at least
            # N virtual s" semantics would extend fast tests to their full
            # deadline instead of capping only hung ones
            try:
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=args.deadline
                )
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "name": str(path),
                        "exit": -1,
                        "output": f"deadline exceeded ({args.deadline:g}s) — hung test\n",
                    }
                )
                if not args.json:
                    print(f"FAIL  {path}")
                continue
        else:
            result = subprocess.run(command, capture_output=True, text=True)
        results.append(
            {
                "name": str(path),
                "exit": result.returncode,
                "output": (result.stdout + result.stderr)[-2000:],
            }
        )
        if not args.json:
            print(f"{'PASS' if result.returncode == 0 else 'FAIL'}  {path}")
    failed = [entry for entry in results if entry["exit"] != 0]
    if args.json:
        print(
            json.dumps(
                {"passed": len(results) - len(failed), "failed": len(failed), "files": results},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"{len(results) - len(failed)} passed, {len(failed)} failed")
        for entry in failed:
            print(f"--- {entry['name']} (exit {entry['exit']}) ---")
            print(entry["output"])
    return 1 if failed else 0
