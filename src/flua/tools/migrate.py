"""``flua --tool migrate`` — one-pass plua-migration scan.

Scans a project directory for plua leftovers and migration hazards, so a
plua → flua conversion ends with a mechanical gate instead of a manual
checklist:

- plua-style directive spellings (``-- %%`` with a space) and plua-only
  directive names (``headers``/``save``/``port``/``conceal``/``desktop``)
  with their flua replacements;
- shell scripts and docs still invoking the ``plua`` binary;
- stale packed artifacts (``dist``-style ``.fqa`` files older than the
  sources, and pre-flua-format packages with ``"type":"lua"`` entries);
- ``--%%var`` directives baking a literal IP address into distribution
  packages (add a package value instead).

Exit 1 when any finding exists (a migration gate for CI); ``--json`` emits
one JSON object per finding for agents.

Usage::

    flua --tool migrate [--json] [DIR]     # DIR defaults to the current directory
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

NAME = "migrate"
HELP = "scan a project for plua leftovers and migration hazards"

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist-build"}
_TEXT_SUFFIXES = {".sh", ".md", ".txt", ".json", ".yml", ".yaml", ".example", ".toml", ".cfg"}

# plua-only directive names -> the flua replacement (None = remove it)
_PLUA_DIRECTIVES = {
    "headers": "--%%include",
    "save": None,
    "port": None,
    "conceal": "--%%clobber",
    "desktop": "--ui / --%%u rows",
}

_PLUA_INVOCATION = re.compile(
    r"(?<!\w)plua\s+(?:-\w|pack|upload|download|run|update|createDB|unpack)\b"
)

_IP_VAR = re.compile(r'--%%var:\s*\w+\s*=\s*"(?:\d{1,3}\.){3}\d{1,3}"')


def _finding(path: Path, line: int, message: str) -> dict[str, str]:
    return {"file": str(path), "line": str(line), "finding": message}


def _scan_file(path: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings
    suffix = path.suffix.lower()
    if suffix == ".lua" or path.name == ".flua-directives":
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if line.startswith("-- %%"):
                findings.append(
                    _finding(
                        path,
                        lineno,
                        "plua-style directive spelling (space before %%): flua ignores "
                        "this line — remove it or respell --%%...",
                    )
                )
                continue
            if re.match(r"^--%%[A-Za-z_][A-Za-z0-9_-]*=", line):
                findings.append(
                    _finding(
                        path,
                        lineno,
                        "legacy directive spelling (--%%name=...): accepted for "
                        "compatibility — respell '--%%name:...'",
                    )
                )
                continue
            match = re.match(r"^--%%([A-Za-z_]+):", line)
            if (
                match
                and match.group(1) == "file"
                and "," not in line
                and ":" in line[len("--%%file:") :]
            ):
                findings.append(
                    _finding(
                        path,
                        lineno,
                        "legacy --%%file:path:name spelling — flua expects "
                        "--%%file:path,name (the colon form treats the whole value as the path)",
                    )
                )
                continue
            if match and match.group(1) in _PLUA_DIRECTIVES:
                name = match.group(1)
                replacement = _PLUA_DIRECTIVES[name]
                findings.append(
                    _finding(
                        path,
                        lineno,
                        f"plua directive --%%{name} — "
                        + (
                            f"accepted as {replacement}; respell"
                            if replacement and name == "headers"
                            else (
                                f"use {replacement} instead"
                                if replacement
                                else "remove it"
                            )
                        ),
                    )
                )
            if _IP_VAR.search(raw) and ',"' not in raw.split("=", 1)[-1]:
                findings.append(
                    _finding(
                        path,
                        lineno,
                        "bakes a literal IP into distributed packages — add a package "
                        'value: --%%var:NAME="ip","<placeholder>"',
                    )
                )
    elif suffix in _TEXT_SUFFIXES:
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _PLUA_INVOCATION.search(line):
                findings.append(
                    _finding(
                        path,
                        lineno,
                        "plua binary invocation — the flua equivalent is "
                        "`flua --tool <name>` (pack SRC -o OUT -f replaces plua -t pack)",
                    )
                )
    return findings


def _scan_fqa(path: Path, newest_source: float) -> list[dict[str, str]]:
    """A packed package: stale when sources are newer, pre-flua format when
    file entries carry "type":"lua"."""
    findings: list[dict[str, str]] = []
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return findings
    if path.stat().st_mtime < newest_source:
        findings.append(
            _finding(path, 1, "stale package — the sources are newer; repack with flua")
        )
    if any(
        isinstance(entry, dict) and entry.get("type") == "lua"
        for entry in package.get("files") or []
    ):
        findings.append(
            _finding(path, 1, "pre-flua-format package (plua file entries) — regenerate")
        )
    return findings


def _scan(root: Path) -> list[dict[str, str]]:
    root = root.resolve()
    findings: list[dict[str, str]] = []
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in _SKIP_DIRS for part in path.parts)
    ]
    newest_source = max(
        (
            path.stat().st_mtime
            for path in files
            if path.suffix.lower() == ".lua" or path.name == ".flua-directives"
        ),
        default=0.0,
    )
    for path in files:
        if path.suffix.lower() == ".fqa":
            findings.extend(_scan_fqa(path, newest_source))
        else:
            findings.extend(_scan_file(path))
    return sorted(findings, key=lambda f: (f["file"], int(f["line"])))


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="project directory to scan (default: the current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object per finding (the agent form)",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    root = Path(args.directory)
    if not root.is_dir():
        parser.error(f"{args.directory} is not a directory")
    findings = _scan(root)
    if args.json:
        for finding in findings:
            print(json.dumps(finding, ensure_ascii=False))
    else:
        for finding in findings:
            print(f"{finding['file']}:{finding['line']}: {finding['finding']}")
        print(f"migrate: {len(findings)} finding(s)")
    return 1 if findings else 0
