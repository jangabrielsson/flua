"""feedback: scaffold, list, and file agent experience reports.

The feedback loop's tool half: agents (often outside the flua repo, with
flua installed as a wheel) scaffold a dated report from the shipped
template into ~/.flua/feedback/, then file it — the preferred channel is
a GitHub issue (`feedback publish` runs gh with the report as the body,
against the repo gh is authenticated for); the fallback is handing the
file back (forum, PR into docs/feedback/). Closing a report sets its
Status line to a pointer (the capabilities entry / test / tool it
became, or a reject reason) — the triage contract in the template and
docs/feedback/README.md.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .. import __version__

NAME = "feedback"
HELP = "agent feedback: scaffold and list experience reports (docs/feedback/)"

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "setup_templates"
    / "docs"
    / "feedback"
    / "TEMPLATE.md"
)


def _feedback_dir() -> Path:
    return Path.home() / ".flua" / "feedback"


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(text).strip().lower()).strip("-")
    return slug or "feedback"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--new",
        action="store_true",
        help="scaffold a dated report in ~/.flua/feedback from the template",
    )
    parser.add_argument("--topic", metavar="SLUG", help="report topic for --new (the file name)")
    parser.add_argument("--list", action="store_true", help="the local reports and their statuses")
    parser.add_argument(
        "--publish",
        metavar="FILE",
        help="file the report as a GitHub issue via gh (needs gh authenticated)",
    )
    parser.add_argument("--template", action="store_true", help="print the report template")
    parser.add_argument("--json", action="store_true", help="machine-readable output (agents)")


def _status_of(text: str) -> str:
    match = re.search(r"^Status:\s*(.+)$", text, re.M)
    status = match.group(1).strip() if match else "unset"
    return re.sub(r"\s*<!--.*$", "", status).strip()


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.template:
        print(_TEMPLATE_PATH.read_text(encoding="utf-8"), end="")
        return 0
    if args.new:
        directory = _feedback_dir()
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{_slug(str(args.topic or 'feedback'))}_flua_{datetime.now():%y_%m_%d}.md"
        path = directory / name
        if path.exists():
            print(f"feedback: {path} already exists", file=sys.stderr)
            return 1
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
        filled = template.replace(
            "Date: <yyyy-mm-dd> · flua <version>",
            f"Date: {datetime.now():%Y-%m-%d} · flua {__version__}",
        )
        path.write_text(filled, encoding="utf-8")
        print(f"wrote {path}")
        return 0
    if args.list:
        directory = _feedback_dir()
        reports = []
        if directory.is_dir():
            for path in sorted(directory.glob("*.md")):
                reports.append(
                    {"name": path.name, "status": _status_of(path.read_text(encoding="utf-8"))}
                )
        if args.json:
            print(json.dumps({"dir": str(directory), "reports": reports}, indent=2))
        else:
            if not reports:
                print(f"no reports yet — {directory}")
            for report in reports:
                print(f"{report['name']}  [{report['status']}]")
        return 0
    if args.publish:
        path = Path(str(args.publish))
        if not path.is_file():
            print(f"feedback: {path} does not exist", file=sys.stderr)
            return 1
        if shutil.which("gh") is None:
            print(
                "feedback: 'gh' (the GitHub CLI) is not installed or not on PATH — "
                "install it, or attach the file to a forum post instead",
                file=sys.stderr,
            )
            return 1
        result = subprocess.run(
            ["gh", "issue", "create", "--label", "feedback", "--body-file", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(
                f"feedback: gh issue create failed: "
                f"{result.stderr.strip() or result.stdout.strip()}",
                file=sys.stderr,
            )
            return 1
        print(result.stdout.strip() or f"issue filed from {path}")
        return 0
    parser.print_help()
    return 1
