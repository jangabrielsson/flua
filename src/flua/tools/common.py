"""Shared helpers for the --tool commands (and ``flua export``)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config import _is_eoh, expand_includes, parse_annotations, split_annotations
from ..engine import LuaEngine
from ..ui import lua_literal


def build_fqa(script: str, *, dist: bool = False) -> tuple[dict[str, Any], None]:
    """Package an unpacked QA project (main file + --%%file extras) as .fqa.

    ``dist`` selects the variable policy: a distribution package (--tool
    pack / ``flua export``) bakes each ``--%%var``'s PACKAGE value where one
    was declared (``--%%var:name=expr,"<placeholder>"`` / ``--%%clobber``),
    the evaluated value otherwise. A personal upload (--tool uploadQA) always
    bakes the real evaluated values — the placeholder is a distribution
    concern, your own HC3 gets the credentials it needs.
    """
    path = Path(script)
    if not path.exists():
        raise FileNotFoundError(f"cannot open {script}: no such file")
    source = path.read_text(encoding="utf-8")
    annotations = expand_includes(parse_annotations(source), path.parent)
    _, local_params = split_annotations(annotations)
    engine = LuaEngine()
    qa_id = engine._prepare_qa(str(path.resolve()), None, local_params, str(path.resolve()))
    fqa = engine.qa_export(qa_id)
    if fqa is None:
        raise ValueError(f"cannot package {script}")
    return _bake_packaged_vars(fqa, source, local_params, engine, dist=dist), None


def _bake_packaged_vars(
    fqa: dict[str, Any],
    source: str,
    local_params: dict[str, Any],
    engine: LuaEngine,
    *,
    dist: bool,
) -> dict[str, Any]:
    """Evaluate --%%var expressions (no QA code runs) and bake the values
    into the package: quickAppVariables in initialProperties, and the main
    file's --%%var header lines rewritten to the baked literals so the file
    content never carries an expression or a secret literal that was not
    meant to travel. Unset (nil) variables are dropped from both."""
    var_exprs = local_params.get("var") or {}
    if not isinstance(var_exprs, dict):
        var_exprs = {}
    var_pkg = local_params.get("varPkg") or {}
    clobber = local_params.get("clobber") or {}
    for name in clobber:
        if name not in var_exprs:
            raise ValueError(
                f"--%%clobber:{name}=... names a variable without a --%%var:{name} directive"
            )
        if name in var_pkg:
            raise ValueError(
                f"--%%var:{name} declares a package value AND a --%%clobber:{name} — use one"
            )
    values = engine.evaluate_vars(var_exprs)
    final: dict[str, Any] = {}
    for name in var_exprs:
        pkg = var_pkg[name] if name in var_pkg else clobber.get(name)
        if dist and pkg is not None:
            final[name] = pkg
        elif name in values:
            final[name] = values[name]
    if final:
        initial = fqa.setdefault("initialProperties", {})
        initial["quickAppVariables"] = [
            {"name": name, "value": _wire_value(value)} for name, value in sorted(final.items())
        ]
    main = next((f for f in fqa.get("files") or [] if f.get("isMain")), None)
    if main is None:
        return fqa
    scrubbed: list[str] = []
    in_header = True
    for line in source.splitlines(keepends=True):
        stripped = line.strip()
        if in_header and _is_eoh(stripped):
            in_header = False
        ending = line[len(line.rstrip("\r\n")) :]
        if in_header and stripped.startswith("--%%var:"):
            name = stripped[len("--%%var:") :].partition("=")[0].strip()
            if name in var_exprs:
                if name in final:
                    scrubbed.append(f"--%%var:{name}={lua_literal(final[name])}{ending}")
                else:  # evaluated nil — not packaged
                    continue
            else:
                scrubbed.append(line)
        elif in_header and stripped.startswith("--%%clobber:"):
            continue  # packaging metadata, never travels
        else:
            scrubbed.append(line)
    main["content"] = "".join(scrubbed)
    return fqa


def _wire_value(value: Any) -> Any:
    """A variable value as the HC3 wants it: scalars as-is, containers
    (table-typed --%%var values) as compact JSON strings."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


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
