"""Shared helpers for the --tool commands (and ``flua export``)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..config import parse_annotations, split_annotations
from ..engine import LuaEngine


def build_fqa(script: str) -> tuple[dict[str, Any], None]:
    """Package an unpacked QA project (main file + --%%file extras) as .fqa."""
    path = Path(script)
    if not path.exists():
        raise FileNotFoundError(f"cannot open {script}: no such file")
    source = path.read_text(encoding="utf-8")
    _, local_params = split_annotations(parse_annotations(source))
    engine = LuaEngine()
    qa_id = engine._prepare_qa(str(path.resolve()), None, local_params, str(path.resolve()))
    fqa = engine.qa_export(qa_id)
    if fqa is None:
        raise ValueError(f"cannot package {script}")
    return fqa, None


def hc3_engine(parser: argparse.ArgumentParser) -> LuaEngine:
    """An online engine — the tools need the real HC3 (credentials from the
    environment chain; the constructor's own error names the requirement)."""
    try:
        return LuaEngine(api_mode="remote")
    except ValueError as exc:
        parser.error(str(exc))


def fqa_files(fqa: dict[str, Any]) -> list[dict[str, Any]]:
    """The file array for PUT /quickApp/{id}/files (the HC3's bulk update)."""
    return [
        {
            "name": entry["name"],
            "type": "lua",
            "isMain": entry["isMain"],
            "content": entry["content"],
        }
        for entry in fqa["files"]
    ]
