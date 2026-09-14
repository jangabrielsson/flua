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


def parse_annotations(source: str) -> dict[str, Any]:
    """Extract ``--%%`` annotations; later lines override earlier ones.

    A parameter whose value contains ``=`` becomes a dict of subparameters
    (``key=value`` pairs, comma-separated); otherwise the value is a scalar.
    """
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
    }
)


def split_annotations(
    annotations: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split annotations into (global_params, local_params)."""
    global_params = {k: v for k, v in annotations.items() if k in GLOBAL_PARAMS}
    local_params = {k: v for k, v in annotations.items() if k not in GLOBAL_PARAMS}
    return global_params, local_params
