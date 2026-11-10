"""Offline static checks for QA files (``flua --check``).

Three layers, all without running the QA:

1. Syntax — the file is compiled through the engine's Lua state.
2. Directives — unknown ``--%%`` names are flagged (the runtime logs a
   warning for them too; --check adds the file context, so a typo costs
   neither a debugging session nor a --check run).
3. Deprecated REST endpoints — a hardcoded list, derived from the API
   reference in docs/specs/hc3-api.json (itself distilled from the official
   swagger; e.g. GET /quickApp/export is deprecated).

Findings are structured dicts — ``{"file", "severity", "message", "line",
"column"}`` with ``line``/``column`` optional (1-based; None when the
location is not known, e.g. a directive inherited from an --%%include
file). ``format_finding`` renders the human-readable form the CLI prints.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import KNOWN_DIRECTIVES, expand_includes, file_name_error, parse_annotations
from .devices import property_specs_for

# (http method, path prefix, advice) — derived from the distilled API
# reference, docs/specs/hc3-api.json.
DEPRECATED_API = [
    ("GET", "/quickApp/export/", "use POST /quickApp/export/{id} instead"),
]


def finding(
    file: str,
    severity: str,
    message: str,
    line: int | None = None,
    column: int | None = None,
) -> dict[str, Any]:
    """One structured finding (line/column omitted from JSON when unknown)."""
    entry: dict[str, Any] = {"file": file, "severity": severity, "message": message}
    if line is not None:
        entry["line"] = line
    if column is not None:
        entry["column"] = column
    return entry


def format_finding(entry: dict[str, Any]) -> str:
    """The human-readable CLI line: ``file: severity: message``."""
    return f"{entry['file']}: {entry['severity']}: {entry['message']}"


def _line_col(source: str, offset: int) -> tuple[int, int]:
    """1-based (line, column) for a character offset into source."""
    line = source.count("\n", 0, offset) + 1
    column = offset - source.rfind("\n", 0, offset)
    return line, column


def _directive_location(source: str, key: str) -> tuple[int, int] | None:
    """The first occurrence of ``--%%key`` in source, or None (the key may
    come from an --%%include file the source only references)."""
    match = re.search(rf"^--%%{re.escape(key)}\b", source, re.MULTILINE)
    return _line_col(source, match.start()) if match else None


def _syntax_location(message: str) -> tuple[int | None, str]:
    """Lua syntax errors read ``name:LINE: message`` — split that apart."""
    match = re.search(r":(\d+):\s*", message)
    if match:
        return int(match.group(1)), message[match.end() :]
    return None, message


def check_source(
    source: str, name: str, lua: Any, base_dir: str | Path = "."
) -> list[dict[str, Any]]:
    """Structured findings for one QA source (see the module docstring)."""
    findings: list[dict[str, Any]] = []
    try:
        lua.compile(source, f"@{name}")  # compile-only: syntax validation
    except Exception as exc:
        line, detail = _syntax_location(str(exc))
        findings.append(finding(name, "error", f"syntax: {detail}", line))
        return findings
    try:
        annotations = expand_includes(
            parse_annotations(source, warn_unknown=False), base_dir
        )
    except ValueError as exc:
        findings.append(finding(name, "error", str(exc)))
        return findings
    for key in annotations:
        if key not in ("varPkg", "svarPkg") and key not in KNOWN_DIRECTIVES:
            loc = _directive_location(source, key)
            findings.append(
                finding(
                    name,
                    "warning",
                    f"unknown directive --%%{key}",
                    *loc if loc else (None, None),
                )
            )
    both = set(annotations.get("var") or {}) & set(annotations.get("svar") or {})
    for var_name in sorted(both):
        loc = re.search(
            rf"^--%%var:\s*{re.escape(var_name)}\s*=", source, re.MULTILINE
        )
        findings.append(
            finding(
                name,
                "warning",
                f"both --%%var and --%%svar declare '{var_name}'"
                " — the secret (--%%svar) wins",
                *_line_col(source, loc.start()) if loc else (None, None),
            )
        )
    # property type checks against the distilled schema: updateProperty
    # with a literal that does not fit the declared type/enum (the HC3
    # is believed to ignore the update — flua warns statically too). Only literal
    # arguments match; expressions stay unchecked.
    qa_type = annotations.get("type")
    prop_specs = property_specs_for(
        qa_type if isinstance(qa_type, str) else None, annotations.get("interface")
    )
    if prop_specs:
        literal_re = r"(?:true|false|\d+(?:\.\d+)?|['\"][^'\"]*['\"])"
        pattern = (
            rf"self\s*:\s*updateProperty\s*\(\s*['\"]([A-Za-z0-9_]+)['\"]"
            rf"\s*,\s*({literal_re})\s*\)"
        )
        for match in re.finditer(pattern, source):
            prop_name, literal = match.group(1), match.group(2)
            spec = prop_specs.get(prop_name)
            if spec is None:
                continue
            if literal in ("true", "false"):
                lua_kind = "bool"
            elif re.fullmatch(r"\d+(?:\.\d+)?", literal):
                lua_kind = "number"
            else:
                lua_kind = "string"
            fits = {
                "int": lua_kind == "number",
                "real": lua_kind == "number",
                "bool": lua_kind == "bool",
                "string": lua_kind == "string",
                # a scalar literal never fits an array/object property
                "array": False,
                "object": False,
            }.get(spec.get("type"))
            if fits is False:
                line, column = _line_col(source, match.start())
                findings.append(
                    finding(
                        name,
                        "warning",
                        f"updateProperty: property {prop_name!r} is declared "
                        f"{spec['type']}, the literal {literal!r} does not fit "
                        "(the real HC3 silently ignores the update)",
                        line,
                        column,
                    )
                )
            enum = spec.get("enum")
            if enum and lua_kind == "string" and literal[1:-1] not in enum:
                line, column = _line_col(source, match.start())
                findings.append(
                    finding(
                        name,
                        "warning",
                        f"updateProperty: property {prop_name!r} value "
                        f"{literal[1:-1]!r} is not one of its declared enum",
                        line,
                        column,
                    )
                )
    # plua-era spelling: a space between the comment dashes and %%. flua's
    # parser only matches "--%%" with no space, so these lines are silently
    # ignored — say so, it is almost always a stale plua directive.
    for match in re.finditer(r"--\s+%%\s*(\S*)", source):
        line, column = _line_col(source, match.start())
        findings.append(
            finding(
                name,
                "warning",
                "plua-style directive spelling (space before %%): "
                f"line {line} — flua parses '--%%' with no space; this line is ignored",
                line,
                column,
            )
        )
    # even older spelling: "--%%name=value" (the pre-plua '=' syntax) is
    # ACCEPTED by the parser — say so, but nudge toward the colon form.
    for match in re.finditer(r"^--%%([A-Za-z_][A-Za-z0-9_-]*)=", source, re.MULTILINE):
        directive = match.group(1)
        line, column = _line_col(source, match.start())
        findings.append(
            finding(
                name,
                "warning",
                f"legacy directive spelling (--%%{directive}=...): "
                f"line {line} — accepted for compatibility; respell as "
                f"'--%%{directive}:...'",
                line,
                column,
            )
        )
    for method, prefix, advice in DEPRECATED_API:
        pattern = rf"api\.{method.lower()}\s*\(\s*['\"]({re.escape(prefix)}[^'\"]*)['\"]"
        for match in re.finditer(pattern, source):
            line, column = _line_col(source, match.start())
            findings.append(
                finding(
                    name,
                    "warning",
                    f"deprecated API: {method} {match.group(1)} — {advice}",
                    line,
                    column,
                )
            )
    return findings


def check_file(path: str, lua: Any) -> list[dict[str, Any]]:
    """Structured findings for one QA project: the main file plus every
    ``--%%file`` include, each with its own file context. A missing include
    is an error (like the runtime's load); ``$name`` entries resolve to
    flua's bundled libraries (src/flua/lua/lib)."""
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
        declared = name.strip()
        name = declared or raw
        if declared and not annotations.get("fqafiles"):
            problem = file_name_error(declared)
            if problem is not None:
                loc = re.search(rf"--%%file:\s*{re.escape(raw)}", source)
                findings.append(
                    finding(
                        path,
                        "error",
                        problem,
                        *_line_col(source, loc.start()) if loc else (None, None),
                    )
                )
                continue
        if not raw:
            continue
        if raw.startswith("$"):
            lib_name = raw[1:].lstrip("/")
            if Path(lib_name).name != lib_name or lib_name in ("", ".", ".."):
                loc = re.search(rf"--%%file:\s*\$\s*{re.escape(lib_name)}", source)
                findings.append(
                    finding(
                        path,
                        "error",
                        f"--%%file:{raw},{name}: bad library name",
                        *_line_col(source, loc.start()) if loc else (None, None),
                    )
                )
                continue
            target = bundled / lib_name
        else:
            target = base / raw
        if not target.is_file():
            hint = ""
            if name == raw and ":" in raw:
                # --%%file:path:name is the legacy plua spelling — flua reads
                # path,name, so the whole value became the path
                hint = " — legacy --%%file:path:name spelling? flua expects --%%file:path,name"
            loc = re.search(rf"--%%file:\s*{re.escape(raw)}", source)
            findings.append(
                finding(
                    path,
                    "error",
                    f"--%%file:{raw},{name}: no such file: {target}{hint}",
                    *_line_col(source, loc.start()) if loc else (None, None),
                )
            )
            continue
        resolved = target.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        include_source = target.read_text(encoding="utf-8")
        findings += check_source(include_source, str(target), lua, target.parent)
    return findings
