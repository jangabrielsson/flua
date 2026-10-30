"""Shared helpers for the --tool commands (and ``flua export``)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config import _is_eoh, expand_includes, parse_annotations, split_annotations
from ..engine import IDENTITY_PROPERTIES, LuaEngine, sanitize_filename
from ..ui import lua_literal


def merge_identity_properties(fqa: dict[str, Any], device: dict[str, Any]) -> None:
    """Copy the identity properties from the live device into the package's
    initialProperties. The HC3's own export omits them, so a downloaded QA
    loses manufacturer/model/... — downloadQA/downloadFQA restore them from
    the device. Only non-empty values are merged (the device's empty
    defaults stay out); the device wins over the export."""
    properties = device.get("properties") or {}
    if not isinstance(properties, dict):
        return
    initial = fqa.setdefault("initialProperties", {})
    if not isinstance(initial, dict):
        return
    for key in IDENTITY_PROPERTIES:
        value = properties.get(key)
        if value not in (None, ""):
            initial[key] = value


def default_fqa_output(script: str | Path, annotations: dict[str, Any]) -> Path:
    """The .fqa output path next to the main file: ``<QA name>.fqa`` — the
    QA's --%%name directive, or MyQA.fqa when it declares none."""
    name = sanitize_filename(str(annotations.get("name") or "MyQA"))
    return Path(script).parent / f"{name}.fqa"


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
    """Evaluate --%%var/--%%svar expressions (no QA code runs) and bake the
    values into the package: quickAppVariables in initialProperties, and the
    main file's --%%var/--%%svar header lines rewritten to the baked
    literals so the file content never carries an expression or a secret
    literal that was not meant to travel. Unset (nil) variables are dropped
    from both. --%%svar entries keep type='password' in the package."""
    var_exprs = local_params.get("var") or {}
    if not isinstance(var_exprs, dict):
        var_exprs = {}
    svar_exprs = local_params.get("svar") or {}
    if not isinstance(svar_exprs, dict):
        svar_exprs = {}
    var_pkg = local_params.get("varPkg") or {}
    svar_pkg = local_params.get("svarPkg") or {}
    clobber = local_params.get("clobber") or {}
    for name in clobber:
        if name not in var_exprs and name not in svar_exprs:
            raise ValueError(
                f"--%%clobber:{name}=... names a variable without a"
                f" --%%var/--%%svar:{name} directive"
            )
        if name in var_pkg or name in svar_pkg:
            raise ValueError(
                f"--%%var/--%%svar:{name} declares a package value AND a"
                f" --%%clobber:{name} — use one"
            )
    exprs = {**var_exprs, **svar_exprs}  # a secret wins over a same-named --%%var
    values = engine.evaluate_vars(exprs)
    final: dict[str, Any] = {}
    for name in exprs:
        pkg = var_pkg.get(name, svar_pkg.get(name))
        if pkg is None:
            pkg = clobber.get(name)
        if dist and pkg is not None:
            final[name] = pkg
        elif name in values:
            final[name] = values[name]
    if final:
        initial = fqa.setdefault("initialProperties", {})
        initial["quickAppVariables"] = [
            {
                "name": name,
                "value": _wire_value(value),
                **({"type": "password"} if name in svar_exprs else {}),
            }
            for name, value in sorted(final.items())
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
        if in_header and (stripped.startswith("--%%var:") or stripped.startswith("--%%svar:")):
            prefix, _, rest = stripped.partition(":")
            name = rest.partition("=")[0].strip()
            if name in exprs:
                if name in final:
                    scrubbed.append(f"{prefix}:{name}={lua_literal(final[name])}{ending}")
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
