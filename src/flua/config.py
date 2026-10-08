"""--%% config annotations parsed from Lua source.

Format (valid Lua comments, so the file still runs anywhere):

    --%%name:value
    --%%name:sub1=val1,sub2=val2,...

Directives form a header at the top of the file. Parsing stops at the
end-of-header comment (the EOH convention), so ``--%%`` lines that appear
later in the file — e.g. inside inline QA code passed to
``_FLUA.loadQAfromString`` — are not picked up:

    --%%name:outer
    -- --------------- EOH ---------------
    local inner = [[ --%%name:inner ]]

Values may be booleans (true/false), numbers, nil, quoted strings, or bare
strings. Parsed here in Python; the result
drives the engine's runtime settings and is also exposed to Lua as
``_PY.config``.
"""

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EOH_RE = re.compile(r"-+\s*EOH\s*-+")


def _is_eoh(line: str) -> bool:
    """End-of-header comment: ``-- --------------- EOH ---------------``."""
    stripped = line.strip()
    if not stripped.startswith("--"):
        return False
    return bool(_EOH_RE.fullmatch(stripped[2:].strip()))


# --%%mode and its legacy aliases form one directive family: a QA that says
# anything about its mode replaces the defaults' mode entirely.
# --%%mode and its legacy aliases form one directive family: a QA that says
# anything about its mode replaces any included file's mode entirely.
_MODE_KEYS = ("mode", "offline", "proxy")

# --%%include:<filepath> — insert another file's directives as defaults for
# this QA (the QA header wins; later includes override earlier ones). The
# path resolves relative to the file that carries the include line.
INCLUDE_DIRECTIVE = "include"


def _merge_defaults(merged: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge ``incoming`` directives over the accumulated defaults.

    Per-key override (a QA's --%%u/--%%var/--%%name replaces the whole
    value); the mode family overrides as a whole; --%%file lists append
    (defaults first, a redeclared file name wins with the later entry).
    """
    if any(key in incoming for key in _MODE_KEYS):
        for key in (*_MODE_KEYS, "proxyNoUI"):
            merged.pop(key, None)
    default_files = merged.get("file")
    incoming_files = incoming.get("file")
    merged.update(incoming)
    if default_files or incoming_files:
        entries = [default_files] if isinstance(default_files, str) else list(default_files or [])
        entries += (
            [incoming_files] if isinstance(incoming_files, str) else list(incoming_files or [])
        )
        by_name: dict[str, str] = {}
        for entry in entries:
            name = entry.partition(",")[2].strip()
            by_name[name] = entry  # later entries win, position stays
        merged["file"] = list(by_name.values())


def expand_includes(annotations: dict[str, Any], base_dir: str | Path) -> dict[str, Any]:
    """Expand --%%include directives: insert the included files' directives
    as defaults for this QA's own header.

    Include paths resolve relative to the file carrying the include line
    (the QA's own includes: relative to the main file's directory); nested
    includes are allowed and resolve the same way. A later include
    overrides an earlier one, and the QA's own directives override all of
    them — the ``--%%file`` lists append (defaults first). Include cycles
    are resolved by skipping the already-included file. A missing or
    unreadable include is an error (it is explicit, unlike the old
    .directives lookup).
    """
    merged: dict[str, Any] = {}
    seen: set[str] = set()

    def absorb(anns: dict[str, Any], directory: Path) -> None:
        includes = anns.pop(INCLUDE_DIRECTIVE, None)
        if includes:
            entries = [includes] if isinstance(includes, str) else list(includes)
            for entry in entries:
                include_path = Path(str(entry).strip())
                if not include_path.is_absolute():
                    include_path = directory / include_path
                resolved = str(include_path.resolve())
                if resolved in seen:
                    continue  # include cycle — the first inclusion wins
                seen.add(resolved)
                try:
                    source = include_path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise ValueError(
                        f"--%%include:{entry}: cannot read {include_path}: {exc}"
                    ) from exc
                absorb(parse_annotations(source), include_path.parent)
        _merge_defaults(merged, anns)

    absorb(dict(annotations), Path(base_dir))
    return _apply_mode(merged)


def parse_scalar(text: str) -> Any:
    text = text.strip()
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("nil", "null", "none"):
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    try:
        if "." in text or "e" in lowered:
            return float(text)
        return int(text)
    except ValueError:
        return text


_LUA_NUMBER_RE = re.compile(r"-?\d+(\.\d+)?([eE][+-]?\d+)?")


def parse_lua_literal(text: str) -> Any:
    """Parse the restricted Lua table-literal syntax used by ``--%%u``
    directives into Python data.

    ``{key=value,...}`` becomes a dict, ``{a,b,...}`` a list. Values may be
    quoted strings (``'..'`` or ``".."``), numbers, true/false/nil, nested
    tables, or bare identifiers (kept as strings — a Lua evaluation
    would silently turn them into nil). This is deliberately NOT a full Lua
    expression evaluator: no function calls, operators, or env lookups.
    """
    tokens = _tokenize_lua_literal(text.strip())
    if not tokens:
        raise ValueError(f"empty --%%u literal: {text!r}")
    value, index = _parse_lua_value(tokens, 0)
    if index != len(tokens):
        raise ValueError(f"trailing content in --%%u literal: {text!r}")
    if not isinstance(value, (dict, list)):
        raise ValueError(f"--%%u literal must be a table: {text!r}")
    return value


def _tokenize_lua_literal(text: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "{},=":
            tokens.append((ch, None))
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.append(nxt if nxt in "'\"\\" else c)
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                buf.append(c)
                i += 1
            else:
                raise ValueError(f"unterminated string in --%%u literal: {text!r}")
            tokens.append(("str", "".join(buf)))
            continue
        if ch.isdigit() or ch == "-":
            j = i + 1
            while j < n and text[j] in "0123456789.eE+-":
                j += 1
            raw = text[i:j]
            if not _LUA_NUMBER_RE.fullmatch(raw):
                raise ValueError(f"invalid number in --%%u literal: {raw!r}")
            tokens.append(("num", float(raw) if ("." in raw or "e" in raw.lower()) else int(raw)))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            word = text[i:j]
            if word == "true":
                tokens.append(("bool", True))
            elif word == "false":
                tokens.append(("bool", False))
            elif word == "nil":
                tokens.append(("nil", None))
            else:
                tokens.append(("ident", word))
            i = j
            continue
        raise ValueError(f"unexpected character {ch!r} in --%%u literal")
    return tokens


def _parse_lua_value(tokens: list[tuple[str, Any]], index: int) -> tuple[Any, int]:
    if index >= len(tokens):
        raise ValueError("unbalanced braces in --%%u literal")
    kind, value = tokens[index]
    if kind == "{":
        return _parse_lua_table(tokens, index)
    if kind in ("str", "num", "bool", "ident", "nil"):
        return value, index + 1
    raise ValueError(f"unexpected {kind!r} in --%%u literal")


def _parse_lua_table(tokens: list[tuple[str, Any]], index: int) -> tuple[Any, int]:
    index += 1  # consume '{'
    pairs: dict[str, Any] = {}
    array: list[Any] = []
    while True:
        if index >= len(tokens):
            raise ValueError("unbalanced braces in --%%u literal")
        kind, value = tokens[index]
        if kind == "}":
            return _lua_table_result(pairs, array), index + 1
        if kind in ("ident", "str") and index + 1 < len(tokens) and tokens[index + 1][0] == "=":
            parsed, index = _parse_lua_value(tokens, index + 2)
            pairs[str(value)] = parsed
        else:
            parsed, index = _parse_lua_value(tokens, index)
            array.append(parsed)
        if index >= len(tokens):
            raise ValueError("unbalanced braces in --%%u literal")
        if tokens[index][0] == ",":
            index += 1
        elif tokens[index][0] != "}":
            raise ValueError("expected ',' or '}' in --%%u literal")


def _lua_table_result(pairs: dict[str, Any], array: list[Any]) -> Any:
    if pairs and array:
        # Lua's array part becomes 1-based integer keys (never used by
        # --%%u rows in practice, but keep the data rather than dropping it)
        for offset, value in enumerate(array, start=1):
            pairs[str(offset)] = value
        return pairs
    return pairs or array


def _brace_balance(text: str) -> int:
    return text.count("{") - text.count("}")


def _join_ui_continuations(source: str) -> str:
    """Merge multi-line ``--%%u`` directives: while the directive's table is
    brace-unbalanced, absorb the following plain comment lines
    continuations like ``--      options={...}``) into the value."""
    lines = source.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("--%%") and stripped[4:].lstrip().startswith("u:"):
            merged = line
            depth = _brace_balance(stripped.split(":", 1)[1])
            while depth > 0 and i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt.startswith("--") and not nxt.startswith("--%%") and not _is_eoh(nxt):
                    content = nxt[2:].strip()
                    merged += " " + content
                    depth += _brace_balance(content)
                    i += 1
                else:
                    break
            out.append(merged)
        else:
            out.append(line)
        i += 1
    return "\n".join(out)


def parse_annotations(source: str, warn_unknown: bool = True) -> dict[str, Any]:
    """Extract ``--%%`` annotations; later lines override earlier ones.

    A parameter whose value contains ``=`` becomes a dict of subparameters
    (``key=value`` pairs, comma-separated); otherwise the value is a scalar.

    Unknown directive names log a warning (pass ``warn_unknown=False`` to
    silence — ``flua --check`` reports them itself in its findings format).
    """
    source = _join_ui_continuations(source)
    config: dict[str, Any] = {}
    for line in source.splitlines():
        stripped = line.strip()
        if _is_eoh(stripped):
            break  # end of the --%% header (EOH convention)
        if not stripped.startswith("--%%"):
            continue
        body = stripped[4:].strip()
        name, sep, value = body.partition(":")
        name = name.strip()
        if not sep or not name:
            continue
        value = value.strip()
        if not value:
            continue
        if warn_unknown and name not in KNOWN_DIRECTIVES:
            # a typo like --%%instnat:true silently changes behavior — say so
            logger.warning("unknown --%% directive: " + stripped)
        if name == "file":
            # --%%file:path,name — declarations load in order, so collect
            # repeated file directives into an ordered list (later lines do
            # not override earlier ones for this parameter).
            existing = config.get("file")
            if not isinstance(existing, list):
                existing = [existing] if existing is not None else []
            existing.append(parse_scalar(value))
            config["file"] = existing
        elif name == "var":
            # --%%var:name=expr — QuickApp variable initializers. The value is
            # a Lua expression, evaluated at bootstrap with {config, os} in
            # scope (so tables like {a=1,b=2} are legal); repeated directives
            # merge, one variable per line.
            sub = config.get("var")
            if not isinstance(sub, dict):
                sub = {}
            key, _, val = value.partition("=")
            key = key.strip()
            if key:
                sub[key] = val.strip()
            config["var"] = sub
        elif name == "property":
            # --%%property:name=value — raw device property initializers
            # (e.g. value=true). Values parse as scalars; repeated
            # directives merge, and several may share one line.
            sub = config.get("property")
            if not isinstance(sub, dict):
                sub = {}
            for part in value.split(","):
                key, _, val = part.partition("=")
                key = key.strip()
                if key:
                    sub[key] = parse_scalar(val)
            config["property"] = sub
        elif name == "u":
            # --%%u:{element...} — one UI row per directive; repeated
            # directives collect in order (like --%%file). The value is a Lua
            # table literal; multi-line rows were joined upstream. A trailing
            # " -- comment" is stripped.
            match = re.match(r"^(.*)\s+--\s+(.*)$", value)
            if match:
                value = match.group(1).rstrip()
            rows = config.get("u")
            if not isinstance(rows, list):
                rows = []
                config["u"] = rows
            rows.append(parse_lua_literal(value))
        elif name == "db":
            # --%%db:house.json — seed the sim from the file; --%%db:+house.json
            # additionally persists emulator state back to it (offline: the
            # whole sim; online: QA state + globalVariables; proxy: seed only)
            db_path = value.strip()
            config["db"] = {
                "path": db_path[1:] if db_path.startswith("+") else db_path,
                "persist": db_path.startswith("+"),
            }
        elif name == "mode":
            # --%%mode:online|offline|proxy[,noUI] — the mode directive; the
            # optional "noUI" (proxy mode only) connects to the existing
            # proxy WITHOUT clobbering its UI (developers who edit the
            # proxy's UI in the HC3's UI editor)
            parts = [part.strip() for part in value.split(",")]
            config["mode"] = parts[0] if parts and parts[0] else None
            if "noUI" in parts:
                config["proxyNoUI"] = True
        elif name == "debug" and "=" not in value:
            # --%%debug:true — enable every debug channel; :false disables
            # them (the full form is --%%debug:api=true,http=true,...).
            # Normalized to the dict shape so consumers can read one shape.
            enabled = parse_scalar(value)
            config["debug"] = {"api": enabled, "http": enabled, "refreshState": enabled}
        elif "=" in value:
            sub: dict[str, Any] = {}
            for part in value.split(","):
                key, _, val = part.partition("=")
                key = key.strip()
                if key:
                    sub[key] = parse_scalar(val)
            config[name] = sub
        else:
            config[name] = parse_scalar(value)
    return _apply_mode(config)


_MODE_VALUES = ("online", "offline", "proxy")


def _apply_mode(config: dict[str, Any]) -> dict[str, Any]:
    """Resolve --%%mode:online|offline|proxy into the engine's flags.

    The single mode directive; the legacy --%%offline:true / --%%proxy:true
    map onto it (an explicit --%%mode wins over both). "offline" pins the
    QA's api.* calls to the sim, "proxy" arms proxy mode (online only), and
    "online" is the plain online behavior. Idempotent — engine callers also
    apply it, so raw config dicts behave like parsed annotations.
    """
    mode = config.get("mode")
    if mode not in _MODE_VALUES:
        mode = None
        if config.get("offline") is True:
            mode = "offline"
        elif config.get("proxy") is True:
            mode = "proxy"
        elif config.get("offline") is False:
            mode = "online"  # legacy --%%offline:false opts INTO online
    if mode is not None:
        config["mode"] = mode
        config["offline"] = mode == "offline"
        config["proxy"] = mode == "proxy"
    return config


# Parameter names that belong to the global (shared) config. When a QA file
# sets one of these, it is copied up to the global config — the last file
# that sets it wins. Everything else stays local to the QA's config copy.
GLOBAL_PARAMS = frozenset(
    {"speed", "instant", "maxhours", "time", "debug", "loglength", "warn"}
)

# Downloaded-file metadata directives (--tool downloadQA writes them, --tool
# uploadFile reads them): the HC3 device id and QA file name a project file
# belongs to, so a single file can be pushed back to its QA without a sidecar.
DEVICE_ID_DIRECTIVE = "deviceId"
QA_FILE_DIRECTIVE = "qaFile"

# Every --%% directive flua understands (globals + locals). --check flags
# anything else, and the runtime parser warns about it too — a typo like
# --%%instnat:true no longer goes silently unnoticed.
KNOWN_DIRECTIVES = frozenset(
    GLOBAL_PARAMS
    | {
        "name",
        "type",
        "properties",
        "property",
        "var",
        "file",
        "mode",
        "offline",  # legacy alias for --%%mode:offline
        "proxy",  # legacy alias for --%%mode:proxy
        "debug",  # --%%debug:refreshState=true,api=true,http=true
        "loglength",  # --%%loglength:120 — debug line length
        "warn",  # --%%warn:true — extra runtime warnings
        "db",  # --%%db:file.json — seed data; +file.json also persists
        "location",  # --%%location:latitude=N,longitude=N — pin the sim's location
        "uid",
        "description",
        "model",
        "build",
        "manufacturer",
        "keep-alive",
        "u",
        "useUiView",
        DEVICE_ID_DIRECTIVE,  # --%%deviceId:123 — downloaded-file metadata (--tool uploadFile)
        QA_FILE_DIRECTIVE,  # --%%qaFile:main — the QA file name a downloaded file maps to
        INCLUDE_DIRECTIVE,  # --%%include:defaults.lua — insert another file's directives
    }
)


def split_annotations(
    annotations: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split annotations into (global_params, local_params)."""
    global_params = {k: v for k, v in annotations.items() if k in GLOBAL_PARAMS}
    local_params = {k: v for k, v in annotations.items() if k not in GLOBAL_PARAMS}
    return global_params, local_params


def debug_flag(config: dict[str, Any], channel: str) -> bool:
    """One ``--%%debug`` channel. The directive is normally a dict of
    channels (``--%%debug:api=true,http=true``); a scalar form is normalized
    at parse time. Defensive against any other shape (a plain bool arrives
    when configs are built by hand, e.g. engine tests) — truthy means all
    channels on."""
    flag = config.get("debug")
    if isinstance(flag, dict):
        return bool(flag.get(channel))
    return bool(flag)


def merge_annotations(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """``extra`` behaves like more ``--%%`` lines appended to a QA's header:
    ``--%%var``/``--%%property`` merge per variable/property, ``--%%u``/
    ``--%%file`` append, everything else overrides.

    This is the semantic for directives passed dynamically at load time
    (``_FLUA.loadQAfromFile(path, {"var:friend=42"})``): they *add* to the
    QA's own header rather than replacing it wholesale.
    """
    merged = dict(base)
    for key, value in extra.items():
        if key in ("var", "property"):
            sub = dict(merged.get(key) or {})
            sub.update(value or {})
            merged[key] = sub
        elif key in ("u", "file"):
            existing = merged.get(key)
            if not isinstance(existing, list):
                existing = [existing] if existing is not None else []
            merged[key] = [*existing, *(value if isinstance(value, list) else [value])]
        else:
            merged[key] = value
    return merged
