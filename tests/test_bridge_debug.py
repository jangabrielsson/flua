"""Bridge-error telemetry: --%%debug:bridge dumps failing payloads and
records a structured bridge_error event (flua-agent-troubleshooting P1/P5)."""

from __future__ import annotations

import pickle

import pytest

pytest.importorskip("lupa")

from flua.bindings import to_lua_table
from flua.engine import LuaEngine


def _engine(bridge_debug: bool) -> LuaEngine:
    engine = LuaEngine()
    if bridge_debug:
        engine.config = {"debug": {"bridge": True}}
    return engine


def _cyclic() -> list:
    data: list = [{"n": 1}]
    data.append(data)  # a cycle: json cannot serialize, pickle can
    return data


def test_bridge_debug_dumps_failing_payload_and_records_event(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("flua.bindings.tempfile.gettempdir", lambda: str(tmp_path))
    engine = _engine(bridge_debug=True)
    lua = engine.lua_runtime()
    with pytest.raises(ValueError):
        to_lua_table(lua, engine, _cyclic(), "GET /devices", qa_id=5000)
    dumps = list(tmp_path.glob("flua-bridge-fail-*.pkl"))
    assert dumps, "a cyclic payload must fall back to a pickle dump"
    # the dump round-trips: it holds the exact payload that failed
    with open(dumps[0], "rb") as handle:
        assert isinstance(pickle.load(handle), list)
    # structured systemLog event (the agent feed)
    events = [e for e in engine.api.state.system_events if e["event"] == "bridge_error"]
    assert len(events) == 1
    assert "type=ValueError" in events[0]["detail"]
    assert "context=GET /devices" in events[0]["detail"]
    assert str(dumps[0]) in events[0]["detail"]
    # and a human-readable flua log line pointing at the dump
    messages = [m["message"] for m in engine.api.state.debug_messages]
    assert any("bridge error:" in text and "payload dumped to" in text for text in messages)


def test_bridge_debug_off_stays_quiet(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("flua.bindings.tempfile.gettempdir", lambda: str(tmp_path))
    engine = _engine(bridge_debug=False)
    lua = engine.lua_runtime()
    with pytest.raises(ValueError):
        to_lua_table(lua, engine, _cyclic(), "GET /devices", qa_id=5000)
    assert not list(tmp_path.glob("flua-bridge-fail-*"))
    assert not [e for e in engine.api.state.system_events if e["event"] == "bridge_error"]
