#!/usr/bin/env python3
"""Generate capabilities/index.json from the curated entries.

Each entry is a markdown file with a front-matter block:

    ---
    id: icons-x-fibaro-version
    topic: hc3-api
    title: ...
    pins:
      - tests/test_hc3.py::test_...
    verified: flua 0.1.167, HC3 5.221
    ---

    # body markdown

The index is generated, never hand-edited — the test suite regenerates
and compares it, so a new entry without a regenerated index fails. The
body stays in the markdown files; the index carries only the metadata.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Split '---\\nkey: value\\n---\\nbody' into (meta, body)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("entry needs a --- front-matter block")
    meta: dict[str, object] = {}
    current: str | None = None
    for index, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if stripped == "---":
            return meta, "\n".join(lines[index + 1 :])
        if stripped.startswith("- "):
            if current is not None:
                existing = meta.get(current)
                if not isinstance(existing, list):
                    existing = []
                    meta[current] = existing
                existing.append(stripped[2:].strip())
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            current = key.strip()
            meta[current] = value.strip()
    raise ValueError("unterminated front-matter block")


def main() -> int:
    root = Path(__file__).resolve().parent.parent / "docs" / "capabilities"
    entries_dir = root / "entries"
    entries: list[dict] = []
    problems: list[str] = []
    for path in sorted(entries_dir.glob("*.md")):
        try:
            meta, _body = parse_front_matter(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{path.name}: {exc}")
            continue
        entry_id = meta.get("id")
        if entry_id != path.stem:
            problems.append(f"{path.name}: id {entry_id!r} != file name")
        if not meta.get("title") or not meta.get("topic"):
            problems.append(f"{path.name}: needs title and topic")
        pins = meta.get("pins")
        if not isinstance(pins, list) or not pins:
            problems.append(f"{path.name}: needs at least one pin")
        entries.append(
            {
                "id": entry_id,
                "topic": meta.get("topic"),
                "title": meta.get("title"),
                "pins": pins if isinstance(pins, list) else [],
                "verified": meta.get("verified", ""),
                "file": f"entries/{path.name}",
            }
        )
    if problems:
        for problem in problems:
            print(f"capabilities problem: {problem}", file=sys.stderr)
        return 1
    out = root / "index.json"
    out.write_text(
        json.dumps({"entries": entries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
