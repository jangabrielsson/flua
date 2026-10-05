"""newQA: scaffold a QuickApp from a standard device type template.

The templates are the quickapp-types skill's ``templates/`` directory (one
file per device type, 41 types, each with the type's canonical actions and
property conventions) — they ship in the wheel, so the tool works for pip
installations too. Types are matched on the template's ``--%%type`` header,
not on file names.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

NAME = "newQA"
HELP = "scaffold a QA from a standard device type template (41 types)"

_TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent
    / "setup_templates"
    / "github"
    / "skills"
    / "quickapp-types"
    / "templates"
)

_PREFIX = "com.fibaro."


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "type",
        nargs="?",
        help="the device type (e.g. binarySwitch, motionSensor — omit to list all)",
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="the QA's --%%name (default: the template's own name)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="output file (default: <type>.lua in the current directory)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite an existing file",
    )


def _templates() -> dict[str, tuple[Path, str]]:
    """{device type (from the --%%type header): (path, source)}."""
    found: dict[str, tuple[Path, str]] = {}
    for path in _TEMPLATES_DIR.glob("*.lua"):
        source = path.read_text(encoding="utf-8")
        match = re.search(r"--%%type:(\S+)", source)
        device_type = match.group(1) if match else path.stem
        found[device_type] = (path, source)
    return found


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    templates = _templates()
    if args.type is None:
        print("available QA templates:")
        for device_type in sorted(templates):
            print(f"  {device_type.removeprefix(_PREFIX)}")
        return 0
    short = args.type.removeprefix(_PREFIX)
    matches = {
        t: v for t, v in templates.items() if t.removeprefix(_PREFIX).lower() == short.lower()
    }
    if not matches:
        matches = {
            t: v for t, v in templates.items() if short.lower() in t.removeprefix(_PREFIX).lower()
        }
    if not matches:
        print(
            f"unknown QA type {args.type!r} — `flua --tool newQA` lists them all",
            file=sys.stderr,
        )
        return 1
    if len(matches) > 1:
        names = ", ".join(t.removeprefix(_PREFIX) for t in sorted(matches))
        print(f"ambiguous type {args.type!r} — matches: {names}", file=sys.stderr)
        return 1
    device_type, (path, source) = next(iter(matches.items()))
    if args.name is not None:
        source = re.sub(r"--%%name:[^\n]*", f"--%%name:{args.name}", source, count=1)
    output = Path(args.output) if args.output else Path(path.name)
    if output.exists() and not args.force:
        print(f"{output} exists — pass --force to overwrite", file=sys.stderr)
        return 1
    output.write_text(source, encoding="utf-8")
    print(f"wrote {output} ({device_type})")
    return 0
