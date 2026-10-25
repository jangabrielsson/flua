"""flua --tool state: the simulator-state dump, alias scan, and tree check."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from flua.api.state import SimState
from flua.tools.state_tool import scan_tree

REPO = Path(__file__).resolve().parent.parent


def _run(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "state", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_state_tool_dump(tmp_path) -> None:
    db = tmp_path / "house.json"
    db.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "id": 10,
                        "name": "Ceiling Lamp",
                        "type": "com.fibaro.binarySwitch",
                        "properties": {"value": False},
                    }
                ]
            }
        )
    )
    result = _run("--db", str(db), cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["devices"][0]["name"] == "Ceiling Lamp"
    assert payload["devices"][0]["properties"]["value"] is False


def test_scan_tree_reports_aliased_objects() -> None:
    # the updateView bug's shape: one list stored at two state paths
    state = SimState(
        {
            "devices": [
                {"id": 10, "name": "a", "type": "com.fibaro.binarySwitch", "properties": {}},
                {"id": 11, "name": "b", "type": "com.fibaro.binarySwitch", "properties": {}},
            ]
        }
    )
    shared = [{"text": "x"}]
    state.devices[10]["properties"]["options"] = shared
    state.devices[11]["properties"]["options"] = shared
    report = scan_tree(state)
    paths = [entry["paths"] for entry in report["aliases"]]
    assert ["devices[10].properties.options", "devices[11].properties.options"] in paths
    assert not report["cycles"]


def test_scan_tree_reports_cycles() -> None:
    state = SimState(
        {
            "devices": [
                {"id": 10, "name": "a", "type": "com.fibaro.binarySwitch", "properties": {}}
            ]
        }
    )
    cyclic: list = [1]
    cyclic.append(cyclic)
    state.devices[10]["properties"]["loop"] = cyclic
    report = scan_tree(state)
    assert report["cycles"], report
    # the cycle is not double-reported as an alias
    assert not [e for e in report["aliases"] if "loop" in str(e["paths"])]


def test_state_tool_verify_and_missing_db(tmp_path) -> None:
    db = tmp_path / "house.json"
    db.write_text(
        json.dumps(
            {
                "devices": [
                    {"id": 10, "name": "a", "type": "com.fibaro.binarySwitch", "properties": {}}
                ]
            }
        )
    )
    result = _run("--db", str(db), "--verify-tree", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no shared references" in result.stdout
    result = _run("--db", "nope.json", cwd=tmp_path)
    assert result.returncode != 0
    assert "cannot read" in result.stderr
