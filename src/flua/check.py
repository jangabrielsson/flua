"""Offline static checks for QA files (``flua --check``).

Three layers, all without running the QA:

1. Syntax — the file is compiled through the engine's Lua state.
2. Directives — unknown ``--%%`` names are flagged (the runtime logs a
   warning for them too; --check adds the file context, so a typo costs
   neither a debugging session nor a --check run).
3. Deprecated REST endpoints — a hardcoded list, derived from the API
   reference in docs/specs/hc3-api.json (itself distilled from the official
   swagger; e.g. GET /quickApp/export is deprecated).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import KNOWN_DIRECTIVES, expand_includes, parse_annotations

# (http method, path prefix, advice) — derived from the distilled API
# reference, docs/specs/hc3-api.json.
DEPRECATED_API = [
    ("GET", "/quickApp/export/", "use POST /quickApp/export/{id} instead"),
]


def check_source(source: str, name: str, lua: Any, base_dir: str | Path = ".") -> list[str]:
    """Findings for one QA source: "name: error: ..." or "name: warning: ..."."""
    findings: list[str] = []
    try:
        lua.compile(source, f"@{name}")  # compile-only: syntax validation
    except Exception as exc:
        findings.append(f"{name}: error: syntax: {exc}")
        return findings
    try:
        annotations = expand_includes(
            parse_annotations(source, warn_unknown=False), base_dir
        )
    except ValueError as exc:
        findings.append(f"{name}: error: {exc}")
        return findings
    for key in annotations:
        if key not in KNOWN_DIRECTIVES:
            findings.append(f"{name}: warning: unknown directive --%%{key}")
    for method, prefix, advice in DEPRECATED_API:
        pattern = rf"api\.{method.lower()}\s*\(\s*['\"]({re.escape(prefix)}[^'\"]*)['\"]"
        for match in re.finditer(pattern, source):
            findings.append(
                f"{name}: warning: deprecated API: {method} {match.group(1)} — {advice}"
            )
    return findings


def check_file(path: str, lua: Any) -> list[str]:
    source = Path(path).read_text(encoding="utf-8")
    return check_source(source, path, lua, Path(path).parent)
