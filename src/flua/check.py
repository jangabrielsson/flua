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
    # plua-era spelling: a space between the comment dashes and %%. flua's
    # parser only matches "--%%" with no space, so these lines are silently
    # ignored — say so, it is almost always a stale plua directive.
    for match in re.finditer(r"--\s+%%\s*(\S*)", source):
        findings.append(
            f"{name}: warning: plua-style directive spelling (space before %%): "
            f"line {source[:match.start()].count(chr(10)) + 1} — flua parses '--%%' "
            "with no space; this line is ignored"
        )
    for method, prefix, advice in DEPRECATED_API:
        pattern = rf"api\.{method.lower()}\s*\(\s*['\"]({re.escape(prefix)}[^'\"]*)['\"]"
        for match in re.finditer(pattern, source):
            findings.append(
                f"{name}: warning: deprecated API: {method} {match.group(1)} — {advice}"
            )
    return findings


def check_file(path: str, lua: Any) -> list[str]:
    """Findings for one QA project: the main file plus every ``--%%file``
    include, each with its own file context. A missing include is an error
    (like the runtime's load); ``$name`` entries resolve to flua's bundled
    libraries (src/flua/lua/lib)."""
    source = Path(path).read_text(encoding="utf-8")
    base = Path(path).parent
    findings = check_source(source, path, lua, base)
    try:
        annotations = expand_includes(parse_annotations(source, warn_unknown=False), base)
    except ValueError:
        return findings  # the include failure is already reported by check_source
    files = annotations.get("file")
    if not isinstance(files, list):
        return findings
    seen = {Path(path).resolve()}
    bundled = Path(__file__).resolve().parent / "lua" / "lib"
    for entry in files:
        # entries are raw "path,name" strings (config's parse_scalar)
        if not isinstance(entry, str):
            continue
        raw, _, name = entry.partition(",")
        raw = raw.strip()
        name = name.strip() or raw
        if not raw:
            continue
        if raw.startswith("$"):
            lib_name = raw[1:].lstrip("/")
            if Path(lib_name).name != lib_name or lib_name in ("", ".", ".."):
                findings.append(f"{path}: error: --%%file:{raw},{name}: bad library name")
                continue
            target = bundled / lib_name
        else:
            target = base / raw
        if not target.is_file():
            findings.append(f"{path}: error: --%%file:{raw},{name}: no such file: {target}")
            continue
        resolved = target.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        include_source = target.read_text(encoding="utf-8")
        findings += check_source(include_source, str(target), lua, target.parent)
    return findings
