"""flua audit: the coverage floors are pinned so they can only go up."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
    assert len(routes["simulated"]) >= 78
    devices = device_coverage()
    assert devices["total"] == 176
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
    assert payload["devices"]["total"] == 176
    assert payload["devices"]["lightModeled"] >= 26
    assert payload["hierarchy"]["total"] == 175
    assert payload["templates"]["total"] == 30
