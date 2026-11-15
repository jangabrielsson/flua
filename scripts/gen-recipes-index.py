#!/usr/bin/env python3
"""Generate recipes/index.json from recipes/*/manifest.json.

The QA builder fetches this index from the flua repo (raw.githubusercontent
— the same channel examples/iconInstall.lua uses), so a new recipe is one
merge, no release. Validates: folder == manifest id, unique ids, main.lua
present, params well-formed (name/label/kind in the known set). Run it
after adding or editing a recipe; the test suite pins index.json against
the manifests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KINDS = {"device", "room", "scene", "number", "text", "boolean"}


def load_manifests(root: Path) -> tuple[list[dict], list[str]]:
    recipes: list[dict] = []
    problems: list[str] = []
    seen: set[str] = set()
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest_path = folder / "manifest.json"
        main_path = folder / "main.lua"
        if not manifest_path.is_file() or not main_path.is_file():
            problems.append(f"{folder.name}: needs manifest.json + main.lua")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{folder.name}: manifest.json is not valid JSON: {exc}")
            continue
        if manifest.get("id") != folder.name:
            problems.append(f"{folder.name}: manifest id {manifest.get('id')!r} != folder name")
        if manifest.get("id") in seen:
            problems.append(f"{folder.name}: duplicate id")
        seen.add(manifest.get("id"))
        if not manifest.get("title") or not manifest.get("description"):
            problems.append(f"{folder.name}: manifest needs a title and a description")
        params = manifest.get("params")
        if not isinstance(params, list) or not params:
            problems.append(f"{folder.name}: manifest needs at least one param")
        for param in params or []:
            if not param.get("name") or not param.get("label"):
                problems.append(f"{folder.name}: a param needs name and label")
            if param.get("kind") not in KINDS:
                problems.append(
                    f"{folder.name}: param {param.get('name')!r} has unknown kind "
                    f"{param.get('kind')!r} (one of {sorted(KINDS)})"
                )
        recipes.append(manifest)
    return recipes, problems


def main() -> int:
    root = Path(__file__).resolve().parent.parent / "recipes"
    recipes, problems = load_manifests(root)
    if problems:
        for problem in problems:
            print(f"recipe problem: {problem}", file=sys.stderr)
        return 1
    out = root / "index.json"
    out.write_text(
        json.dumps({"recipes": recipes}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(recipes)} recipes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
