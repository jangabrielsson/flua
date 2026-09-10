"""--%% config annotations parsed from Lua source.

Format (valid Lua comments, so the file still runs anywhere):

    --%%name:value
    --%%name:sub1=val1,sub2=val2,...

Values may be booleans (true/false), numbers, nil, quoted strings, or bare
strings. Parsed here in Python (unlike plua, which parses in Lua); the result
drives the engine's runtime settings and is also exposed to Lua as
``_PY.config``.
"""

from typing import Any


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
        if "=" in value:
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


def split_annotations(
    annotations: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split annotations into (global_params, local_params)."""
    global_params = {k: v for k, v in annotations.items() if k in GLOBAL_PARAMS}
    local_params = {k: v for k, v in annotations.items() if k not in GLOBAL_PARAMS}
    return global_params, local_params
