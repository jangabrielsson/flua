"""The parity oracle's comparison engine.

``shape`` reduces a JSON value to its structure (field names + types,
concrete values ignored) so the same endpoint response from the sim and
the real HC3 can be compared without house-specific values polluting the
diff. ``drift`` compares two shapes and classifies every difference as a
*problem* or a *gap*:

- problems — the offline (sim) side has fields the HC3 lacks, or type
  mismatches on common fields: real compatibility bugs;
- gaps — the live HC3 has fields the sim does not model: the sim is an
  incomplete subset (catalog-capture limits), reported but not failed.

Extracted from ``tests/test_hc3_compat.py`` (2026-11-04); that suite and
the future capture/replay harness share this module.
"""

from __future__ import annotations


def shape(value) -> object:
    """JSON structure, ignoring concrete values: field names + types."""
    if isinstance(value, dict):
        return {key: shape(val) for key, val in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return "str"


def drift(offline: object, live: object, path: str = "") -> tuple[list[str], list[str]]:
    """(problems, gaps) between two JSON structures. Problems are offline-only
    fields and type mismatches on common fields — real compat bugs. Gaps are
    fields the live HC3 has and the sim lacks — the sim is an incomplete
    subset (catalog-capture limits), reported but not failed."""
    problems: list[str] = []
    gaps: list[str] = []
    if isinstance(live, dict):
        if not isinstance(offline, dict):
            problems.append(f"{path or '/'}: offline={type(offline).__name__}, live=object")
            return problems, gaps
        for key in sorted(set(live) - set(offline)):
            gaps.append(f"{path}.{key}: missing offline (live has {shape(live[key])!r})")
        for key in sorted(set(offline) - set(live)):
            problems.append(f"{path}.{key}: only offline (live lacks it)")
        for key in sorted(set(live) & set(offline)):
            sub_problems, sub_gaps = drift(offline[key], live[key], f"{path}.{key}")
            problems += sub_problems
            gaps += sub_gaps
    elif isinstance(live, list):
        if not isinstance(offline, list):
            problems.append(f"{path or '/'}: offline={type(offline).__name__}, live=list")
        elif live and offline:
            sub_problems, sub_gaps = drift(offline[0], live[0], f"{path}[]")
            problems += sub_problems
            gaps += sub_gaps
    else:
        expected = shape(live)
        actual = shape(offline)
        if actual != expected:
            problems.append(f"{path or '/'}: offline={actual!r}, live={expected!r}")
    return problems, gaps
