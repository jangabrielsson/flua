"""flua --tool house: devices/globals/scenes/customEvents as one JSON document."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

ROOMS = [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living room"}]
DEVICES = [
    {
        "id": 45,
        "name": "Kitchen light",
        "type": "com.fibaro.binarySwitch",
        "roomID": 1,
        "interfaces": ["light"],
    },
    {
        "id": 57,
        "name": "Heating",
        "type": "com.fibaro.deviceController",
        "roomID": 2,
        "interfaces": ["quickApp"],
    },
    {"id": 12, "name": "No room", "type": "com.fibaro.binarySwitch", "interfaces": []},
]
GLOBALS = [{"name": "AlarmState", "value": "disarmed"}, {"name": "Presence", "value": "home"}]
SCENES = [{"id": 3, "name": "Evening lights"}, {"id": 1, "name": "Morning"}]
EVENTS = ["DoorOpened", {"name": "Motion"}]


class _MockHub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        bodies = {
            "/api/rooms": ROOMS,
            "/api/devices": DEVICES,
            "/api/globalVariables": GLOBALS,
            "/api/scenes": SCENES,
            "/api/customEvents": EVENTS,
        }
        if path not in bodies:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(bodies[path]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def _scrubbed() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HC3_URL", "HC3_HOST", "HC3_USER", "HC3_PASSWORD"):
        env.pop(key, None)
    return env


def _run(*argv: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "house", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env if env is not None else _scrubbed(),
    )


def _fake_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))


def test_house_from_hub(tmp_path, monkeypatch) -> None:
    _fake_home(tmp_path, monkeypatch)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHub)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        (tmp_path / ".env").write_text(
            f"HC3_URL=http://127.0.0.1:{server.server_address[1]}\n"
            "HC3_USER=admin\nHC3_PASSWORD=secret\n"
        )
        result = _run(cwd=tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        doc = json.loads(result.stdout)
        assert [d["id"] for d in doc["devices"]] == [12, 45, 57]
        assert doc["devices"][1]["room"] == "Kitchen"
        assert doc["devices"][2]["room"] == "Living room"
        assert doc["devices"][0]["room"] is None
        assert doc["globals"] == ["AlarmState", "Presence"]
        assert doc["scenes"] == [{"id": 1, "name": "Morning"}, {"id": 3, "name": "Evening lights"}]
        assert doc["customEvents"] == ["DoorOpened", "Motion"]
    finally:
        server.shutdown()
        server.server_close()


def test_house_from_seed_file(tmp_path, monkeypatch) -> None:
    _fake_home(tmp_path, monkeypatch)
    seed = tmp_path / "house.json"
    seed.write_text(
        json.dumps(
            {
                "devices": [
                    {"id": 10, "name": "Ceiling Lamp", "type": "com.fibaro.binarySwitch",
                     "roomID": 4},
                    {"id": 11, "name": "Motion", "type": "com.fibaro.motionSensor",
                     "roomID": None},
                ],
                "rooms": [{"id": 4, "name": "Hall"}],
                "scenes": [{"id": 7, "name": "Night"}],
                "globalVariables": {"Away": {"value": "false"}},
            }
        )
    )
    result = _run("--db", str(seed), cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    # the sim always has the controller (device 1), like the real hub
    assert [d["id"] for d in doc["devices"]] == [1, 10, 11]
    assert doc["devices"][1]["room"] == "Hall"
    assert doc["devices"][2]["room"] is None
    assert doc["globals"] == ["Away"]
    assert doc["scenes"] == [{"id": 7, "name": "Night"}]
    assert doc["customEvents"] == []


def test_house_without_hub_or_db_is_empty(tmp_path, monkeypatch) -> None:
    _fake_home(tmp_path, monkeypatch)
    result = _run(cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "devices": [],
        "globals": [],
        "scenes": [],
        "customEvents": [],
    }
