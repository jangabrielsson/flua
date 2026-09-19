"""--%% config annotations parsed from Lua source.

Format (valid Lua comments, so the file still runs anywhere):

    --%%name:value
    --%%name:sub1=val1,sub2=val2,...

Directives form a header at the top of the file. Parsing stops at the
end-of-header comment (the plua convention), so ``--%%`` lines that appear
later in the file — e.g. inside inline QA code passed to
``_FLUA.loadQAfromString`` — are not picked up:

    --%%name:outer
    -- --------------- EOH ---------------
    local inner = [[ --%%name:inner ]]

Values may be booleans (true/false), numbers, nil, quoted strings, or bare
strings. Parsed here in Python (unlike plua, which parses in Lua); the result
drives the engine's runtime settings and is also exposed to Lua as
``_PY.config``.
"""

import re
from typing import Any

_EOH_RE = re.compile(r"-+\s*EOH\s*-+")


def _is_eoh(line: str) -> bool:
    """End-of-header comment: ``-- --------------- EOH ---------------``."""
    stripped = line.strip()
    if not stripped.startswith("--"):
        return False
    return bool(_EOH_RE.fullmatch(stripped[2:].strip()))


_OFFLINE_RE = re.compile(r"^--%%offline\s*:\s*true\s*$")


def peek_offline(source: str) -> bool:
    """Peek at a QA file's raw header for --%%offline:true — plua behavior:
    the engine mode is decided from this peek BEFORE the standard annotation
    parse (which happens once the engine is running)."""
    for line in source.splitlines():
        stripped = line.strip()
        if _is_eoh(stripped) or (stripped and not stripped.startswith("--")):
            break  # end of the directive header
        if _OFFLINE_RE.match(stripped):
            return True
    return False


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
    tables, or bare identifiers (kept as strings — plua's Lua evaluation
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
    brace-unbalanced, absorb the following plain comment lines (plua-style
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


def parse_annotations(source: str) -> dict[str, Any]:
    """Extract ``--%%`` annotations; later lines override earlier ones.

    A parameter whose value contains ``=`` becomes a dict of subparameters
    (``key=value`` pairs, comma-separated); otherwise the value is a scalar.
    """
    source = _join_ui_continuations(source)
    config: dict[str, Any] = {}
    for line in source.splitlines():
        stripped = line.strip()
        if _is_eoh(stripped):
            break  # end of the --%% header (plua EOH convention)
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
            # " -- comment" is stripped (plua behavior).
            match = re.match(r"^(.*)\s+--\s+(.*)$", value)
            if match:
                value = match.group(1).rstrip()
            rows = config.get("u")
            if not isinstance(rows, list):
                rows = []
                config["u"] = rows
            rows.append(parse_lua_literal(value))
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
    return config


# Parameter names that belong to the global (shared) config. When a QA file
# sets one of these, it is copied up to the global config — the last file
# that sets it wins. Everything else stays local to the QA's config copy.
GLOBAL_PARAMS = frozenset({"speed", "instant", "maxhours", "time"})

# Every --%% directive flua understands (globals + locals). --check flags
# anything else — a typo like --%%instnat:true is silently ignored today.
KNOWN_DIRECTIVES = frozenset(
    GLOBAL_PARAMS
    | {
        "name",
        "type",
        "properties",
        "property",
        "var",
        "file",
        "uid",
        "description",
        "model",
        "build",
        "manufacturer",
        "keep-alive",
        "u",
        "useUiView",
    }
)


def split_annotations(
    annotations: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split annotations into (global_params, local_params)."""
    global_params = {k: v for k, v in annotations.items() if k in GLOBAL_PARAMS}
    local_params = {k: v for k, v in annotations.items() if k not in GLOBAL_PARAMS}
    return global_params, local_params
