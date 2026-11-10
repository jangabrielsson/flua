"""flua audit: the coverage floors are pinned so they can only go up."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from flua.api import route_match
from flua.audit import (
    device_coverage,
    hierarchy_coverage,
    route_coverage,
    spec_endpoints,
    template_coverage,
)

REPO = Path(__file__).resolve().parent.parent


def test_audit_pins_the_coverage_floor() -> None:
    # the spec itself: exact, so a regenerated/drifted spec is noticed
    routes = route_coverage()
    assert routes["total"] == len(spec_endpoints()) == 356
    # bump these when coverage grows — shrinking them must fail CI
    assert len(routes["simulated"]) >= 89  # 78 route-table + 11 engine-backed quickApp
    # the engine-backed /quickApp/* endpoints count as simulated (they are
    # served by Api._dispatch, not the route table)
    assert route_match("GET", "/quickApp/5000/files")
    assert route_match("GET", "/quickApp/5000/files/main.lua")
    assert route_match("DELETE", "/quickApp/5000/files/other.lua")
    assert not route_match("GET", "/quickApp/nonsense")
    devices = device_coverage()
    assert devices["total"] == 190  # 189 schema types + the capture-only fallback (pko)
    assert len(devices["lightModeled"]) >= 26
    hierarchy = hierarchy_coverage()
    assert hierarchy["total"] == 175  # exact, like the spec: regeneration is noticed
    assert hierarchy["resolvable"] >= 175
    templates = template_coverage()
    assert templates["total"] == 30  # exact, like the spec
    assert len(templates["resolvable"]) == templates["total"]  # every template must resolve


def test_audit_command_runs(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "flua", "audit"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "of 356 simulated" in result.stdout
    assert "light-modeled" in result.stdout
    result = subprocess.run(
        [sys.executable, "-m", "flua", "audit", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["routes"]["total"] == 356
    assert payload["routes"]["simulated"] >= 78
    assert isinstance(payload["routes"]["missing"], int)  # the plain JSON keeps the count
    assert payload["devices"]["total"] == 190
    assert payload["devices"]["lightModeled"] >= 26
    assert payload["hierarchy"]["total"] == 175
    assert payload["templates"]["total"] == 30


def test_audit_verbose_lists_missing_endpoints(tmp_path) -> None:
    # --verbose: METHOD /path for every endpoint the sim does not implement,
    # and the same list inside the --json output's routes.missing
    result = subprocess.run(
        [sys.executable, "-m", "flua", "audit", "--verbose"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "not simulated endpoints:" in result.stdout
    # a known-missing endpoint appears as METHOD /path
    assert "DELETE /alarms/v1/partitions/{partitionID}" in result.stdout
    result = subprocess.run(
        [sys.executable, "-m", "flua", "audit", "--json", "--verbose"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    missing = payload["routes"]["missing"]
    assert isinstance(missing, list) and missing
    assert {"method": "DELETE", "path": "/alarms/v1/partitions/{partitionID}"} in missing
    # every entry is a two-field method/path pair
    assert all(set(entry) == {"method", "path"} for entry in missing)
