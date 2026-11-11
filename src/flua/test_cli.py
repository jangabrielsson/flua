"""``flua test`` — discover and run self-asserting test QAs.

Each test QA is a normal flua QA that asserts its own behavior and exits —
exit 0 = pass, non-zero = fail (the quickapp-test pattern; see USAGE.md).
The runner discovers ``*_test.lua`` files (hidden directories skipped),
runs each in its own flua process — isolation plus a wall-clock timeout per
file, since a test that never exits must not block the rest — and reports
PASS/FAIL/TIMEOUT. The process exit code is 0 only when everything passes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_TIMEOUT = 30
_OUTPUT_CAP = 20_000


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "paths",
        nargs="*",
        help="test QA files or directories (default: the current directory, "
        "discovering *_test.lua)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the discovered files and exit",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=f"wall-clock limit per test file (default {DEFAULT_TIMEOUT}; a test "
        "QA must exit itself — t:finish()/exit(...))",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show each failed test's output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="one JSON document (files + results + summary) — the machine contract "
        "for the VS Code test adapter and agents",
    )


def discover(paths: list[str], cwd: Path) -> list[Path]:
    """Files to run: explicit file args as-is; directories scanned
    recursively for ``*_test.lua`` with hidden directories skipped."""
    roots = [cwd / path for path in paths] if paths else [cwd]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(str(root))
        if root.is_file():
            files.append(root.resolve())
            continue
        for path in sorted(root.rglob("*_test.lua")):
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            files.append(path.resolve())
    return list(dict.fromkeys(files))


def run_one(path: Path, timeout: int, cwd: Path) -> tuple[str, str, int | None, str]:
    """Run one test QA in its own flua process.

    Returns (stdout, stderr, exit_code, status); status is "ok" or
    "timeout" (the process was killed)."""
    process = subprocess.Popen(
        [sys.executable, "-m", "flua", "--api", "local", str(path)],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return stdout, stderr, process.returncode, "ok"
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        return stdout, stderr, None, "timeout"


def _display(path: Path, cwd: Path) -> str:
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return str(path)


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        files = discover(args.paths, cwd)
    except FileNotFoundError as exc:
        parser.error(str(exc))
    if args.list:
        for path in files:
            print(path)
        return 0
    if not files:
        print("flua test: no *_test.lua files found")
        return 0
    passed = failed = timed_out = 0
    passed_assertions = failed_assertions = 0
    results: list[dict] = []
    for path in files:
        stdout, stderr, code, status = run_one(path, args.timeout, cwd)
        entry: dict = {
            "file": _display(path, cwd),
            "status": "pass",
            "exitCode": code,
            "failures": None,
            "assertionsPassed": 0,
            "assertionsFailed": 0,
            "output": "",
        }
        # structural assertion totals: the flua-test convention prints one
        # "PASS: <msg>" / "FAIL: <msg>" line per assertion — counting them
        # beats grepping the trailing "failures: N" prose (which vanishes
        # when a QA ends differently)
        assertion_passes = len(re.findall(r"\bPASS:\s", stdout))
        assertion_fails = len(re.findall(r"\bFAIL:\s", stdout))
        entry["assertionsPassed"] = assertion_passes
        entry["assertionsFailed"] = assertion_fails
        passed_assertions += assertion_passes
        failed_assertions += assertion_fails
        output = (stderr + stdout).strip()
        output = re.sub(r"\x1b\[[0-9;]*m", "", output)  # no ANSI in the machine output
        if len(output) > _OUTPUT_CAP:
            output = output[:_OUTPUT_CAP] + "\n…(truncated)"
        entry["output"] = output
        if status == "timeout":
            timed_out += 1
            entry["status"] = "timeout"
            if not args.json:
                print(
                    f"  TIME  {_display(path, cwd)}  (no exit within {args.timeout}s — "
                    "does the test end with t:finish()/exit(...)?)"
                )
        elif code == 0:
            passed += 1
            if not args.json:
                print(f"  PASS  {_display(path, cwd)}")
        else:
            failed += 1
            entry["status"] = "fail"
            match = re.search(r"failures: (\d+)", stdout)
            entry["failures"] = (
                assertion_fails if assertion_fails else (int(match.group(1)) if match else None)
            )
            if not args.json:
                print(
                    f"  FAIL  {_display(path, cwd)}  "
                    f"(failures: {match.group(1) if match else '?'})"
                )
                if args.verbose:
                    for line in (stderr + stdout).splitlines():
                        print(f"        {line}")
        results.append(entry)
    if args.json:
        print(
            json.dumps(
                {
                    "files": results,
                    "summary": {"passed": passed, "failed": failed, "timedOut": timed_out},
                    "assertions": {
                        "passed": passed_assertions,
                        "failed": failed_assertions,
                    },
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"flua test: {passed} passed, {failed} failed, {timed_out} timed out")
    return 0 if not failed and not timed_out else 1
