"""inspectFQA: report what a packed .fqa contains, for humans and agents.

The "did my pack come out right" check: metadata, file inventory, the
apiVersion marker, variables (placeholder vs baked literal), the UI
surface, and a leak scan for values that look like real IPs. Exit 1 on
structural errors; warnings are for judgment, not failure (a literal IP
may be intentional).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

NAME = "inspectFQA"
HELP = "inspect a packed .fqa: metadata, inventory, variables, leak scan"

_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_PLACEHOLDER_RE = re.compile(r"^<[^>]*>$")
_UNEVALUATED_RE = re.compile(r"os\.getenv\(|config\.")


def inspect_fqa(fqa: dict[str, Any]) -> dict[str, Any]:
    """One .fqa dict -> the report (never raises — broken input becomes
    errors)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(fqa, dict):
        return {"errors": ["not a JSON object"], "warnings": []}

    name = fqa.get("name")
    files = fqa.get("files") if isinstance(fqa.get("files"), list) else []
    if not files:
        errors.append("no files in the package")
    main = next((f for f in files if isinstance(f, dict) and f.get("isMain")), None)
    if files and main is None:
        errors.append("no main file (isMain) in the package")
    if not name:
        errors.append("no name")

    initial = fqa.get("initialProperties") if isinstance(fqa.get("initialProperties"), dict) else {}
    marker = initial.get("apiVersion")
    if not marker:
        warnings.append(
            "no initialProperties.apiVersion — the HC3 treats the package as legacy "
            "and re-derives uiCallbacks (custom UI handlers get dropped)"
        )

    variables: list[dict[str, Any]] = []
    for var in initial.get("quickAppVariables") or []:
        if not isinstance(var, dict):
            continue
        value = var.get("value")
        entry: dict[str, Any] = {
            "name": str(var.get("name")),
            "value": value,
            "type": var.get("type"),
            "placeholder": bool(isinstance(value, str) and _PLACEHOLDER_RE.fullmatch(value)),
        }
        variables.append(entry)
        if isinstance(value, str):
            if _UNEVALUATED_RE.search(value):
                errors.append(
                    f"variable {entry['name']!r} still carries an unevaluated "
                    f"expression: {value!r}"
                )
            if _IP_RE.search(value):
                warnings.append(
                    f"variable {entry['name']!r} holds what looks like a real IP: "
                    f"{value!r} — intentional literals are fine, secrets are not"
                )

    view = initial.get("viewLayout") if isinstance(initial.get("viewLayout"), dict) else {}
    rows = view.get("rows") if isinstance(view.get("rows"), list) else []
    callbacks = (
        initial.get("uiCallbacks")
        if isinstance(initial.get("uiCallbacks"), list)
        else []
    )

    return {
        "name": name,
        "type": fqa.get("type"),
        "files": [
            {
                "name": str(f.get("name")),
                "isMain": bool(f.get("isMain")),
                "bytes": len(f.get("content") or ""),
            }
            for f in files
            if isinstance(f, dict)
        ],
        "apiVersion": marker,
        "interfaces": fqa.get("initialInterfaces"),
        "ui": {
            "rows": len(rows),
            "callbacks": len(callbacks),
            "uiView": "uiView" in initial,
        },
        "variables": variables,
        "warnings": warnings,
        "errors": errors,
    }


def _format(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"name: {report.get('name')}")
    lines.append(f"type: {report.get('type')}")
    files = report.get("files") or []
    files_text = ", ".join(
        f"{f['name']}{' (main)' if f['isMain'] else ''} {f['bytes']}B" for f in files
    )
    lines.append(f"files: {files_text or 'none'}")
    lines.append(f"apiVersion: {report.get('apiVersion') or '(missing)'}")
    ui = report.get("ui") or {}
    lines.append(
        f"ui: {ui.get('rows')} row(s), {ui.get('callbacks')} callback(s), "
        f"uiView={'yes' if ui.get('uiView') else 'no'}"
    )
    for var in report.get("variables") or []:
        lines.append(
            f"variable: {var['name']} = {var['value']!r}"
            f"{' (placeholder)' if var['placeholder'] else ''}"
        )
    for warning in report.get("warnings") or []:
        lines.append(f"warning: {warning}")
    for error in report.get("errors") or []:
        lines.append(f"error: {error}")
    errors = len(report.get("errors") or [])
    warnings = len(report.get("warnings") or [])
    lines.append(f"inspectFQA: {warnings} warning(s), {errors} error(s)")
    return "\n".join(lines)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("package", help="the .fqa file to inspect")
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable report (agents); exit 1 on errors",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    path = Path(args.package)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        parser.error(f"cannot open {args.package}: {exc}")
    except ValueError as exc:
        parser.error(f"{args.package}: not valid JSON: {exc}")
    report = inspect_fqa(body)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if report["errors"] else 0
    print(_format(report))
    return 1 if report["errors"] else 0
