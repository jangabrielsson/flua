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
    simdevices = root.parent / "src" / "flua" / "simdevices"
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
        categories = manifest.get("categories")
        if not isinstance(categories, list) or not categories or not all(
            isinstance(c, str) and c for c in categories
        ):
            problems.append(f"{folder.name}: manifest needs non-empty string categories")
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
        # simDevices: extra bundled sim devices the sim run loads so the
        # user can drive the recipe's world (the weatherMgr for a weather
        # recipe) — every name must exist in src/flua/simdevices
        sim_devices = manifest.get("simDevices")
        if sim_devices is not None and (
            not isinstance(sim_devices, list)
            or not all(isinstance(name, str) and name for name in sim_devices)
        ):
            problems.append(f"{folder.name}: simDevices must be a list of names")
        for name in sim_devices or []:
            if not (simdevices / f"{name}.lua").is_file():
                problems.append(f"{folder.name}: unknown sim device {name!r}")
        # verify: the declarative scenario flua --tool build --verify runs
        verify = manifest.get("verify")
        if verify is not None:
            steps = verify.get("steps") if isinstance(verify, dict) else None
            if not isinstance(steps, list) or not steps:
                problems.append(f"{folder.name}: verify needs a non-empty steps list")
            else:
                kinds = ("device", "slider", "weather", "wait", "check")
                for step in steps:
                    used = [k for k in kinds if k in step]
                    if len(used) != 1:
                        problems.append(
                            f"{folder.name}: a verify step needs exactly one of "
                            "device/slider/weather/wait/check"
                        )
                    elif used[0] == "device" and not isinstance(step.get("call"), str):
                        problems.append(f"{folder.name}: a device step needs a call")
                    elif used[0] == "check" and not isinstance(step.get("check"), dict):
                        problems.append(f"{folder.name}: a check step needs device/log")
                start = verify.get("start")
                if start is not None and (
                    not isinstance(start, dict) or start.get("before") != "sunset"
                ):
                    problems.append(
                        f"{folder.name}: verify start must be {{before='sunset', by='2m'}}"
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
