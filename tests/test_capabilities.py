"""The capabilities index: generated, pinned, agent-facing.

The index (docs/capabilities/index.json) is generated from the curated
entries; these tests regenerate + compare it and check that every entry's
``pins`` resolve — a renamed/deleted pinning test fails here, so entries
cannot rot silently into fiction."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from flua.capabilities import derived, entries, get_entry, load_index, search

REPO = Path(__file__).resolve().parent.parent


def test_capabilities_index_matches_the_entries() -> None:
    # the checked-in index.json must equal the generator's output — a new
    # entry without a regenerated index fails here, not in the field
    result = subprocess.run(
        [sys.executable, "scripts/gen-capabilities-index.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert (REPO / "docs" / "capabilities" / "index.json").read_text(encoding="utf-8") == (
        REPO / "src" / "flua" / "setup_templates" / "docs" / "capabilities" / "index.json"
    ).read_text(encoding="utf-8"), "run scripts/sync-skills.sh — the packaged index drifted"


def test_every_capability_entry_resolves_its_pins() -> None:
    # every curated entry must prove itself: at least one pin, and each pin
    # must resolve to an existing file (and a test name present in it) —
    # an entry whose proof was renamed or deleted fails loudly
    index = load_index()
    assert index["entries"], "the capabilities index is empty"
    for entry in index["entries"]:
        entry_id = entry["id"]
        pins = entry.get("pins")
        assert pins, f"{entry_id}: no pins"
        assert entry.get("title") and entry.get("topic"), f"{entry_id}: needs title/topic"
        body = get_entry(entry_id)
        assert body and body["body"].strip(), f"{entry_id}: missing body"
        for pin in pins:
            path, _, test_name = pin.partition("::")
            target = REPO / path
            assert target.is_file(), f"{entry_id}: pin {pin!r} does not resolve"
            if test_name:
                assert test_name in target.read_text(encoding="utf-8"), (
                    f"{entry_id}: pin {pin!r} names a missing test"
                )


def test_capabilities_search_ranks_and_gets() -> None:
    # the agent channel: search by terms, read the full entry back
    hits = search("websocket push")
    assert hits and hits[0]["id"] == "websocket-server-push"
    entry = get_entry("readonly-modes")
    assert entry is not None
    assert "--%%mode:readonly" in entry["body"]
    assert json.loads(json.dumps(load_index()))["entries"][0]["id"] == entries()[0]["id"]


def test_capabilities_derived_sections_are_assembled() -> None:
    # the machine-derived half: tools, sim devices, and the REST table —
    # the same sources --capabilities-json reads, so they cannot disagree
    data = derived()
    names = [tool["name"] for tool in data["tools"]]
    assert "caps" in names and "icons" in names and "build" in names
    sims = {device["name"]: device for device in data["simDevices"]}
    assert sims["motionSensor"]["type"] == "com.fibaro.motionSensor"
    assert sims["weatherMgr"]["type"] == "com.fibaro.genericDevice"
    routes = {(route["method"], route["path"]) for route in data["rest"]}
    assert ("GET", "/devices") in routes
    assert ("POST", "/devices/{id}/action/{action}") in routes
    assert any(route["status"] == "stub" for route in data["rest"])


def test_capabilities_search_covers_the_derived_sections() -> None:
    # search spans curated entries AND the machine surface: tools by name,
    # sim devices by type/description, REST routes by path
    hits = search("downloadQA")
    assert any(hit["kind"] == "tool" and hit["id"] == "downloadQA" for hit in hits)
    hits = search("motionSensor")
    assert any(hit["kind"] == "sim" and hit["id"] == "motionSensor" for hit in hits)
    hits = search("refreshStates")
    assert any(hit["kind"] == "rest" and "refreshStates" in hit["id"] for hit in hits)
