"""flua record / --replay: capture a real house session and replay it offline."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


class _MockHc3(BaseHTTPRequestHandler):
    """/devices + /settings/info snapshots; /refreshStates flips a value per poll."""

    polls = 0

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/devices":
            self._send(
                [
                    {
                        "id": 10,
                        "name": "lamp",
                        "type": "com.fibaro.binarySwitch",
                        "properties": {"value": False},
                    }
                ]
            )
        elif path == "/api/settings/info":
            self._send({"hcName": "my-hc3"})
        elif path == "/api/refreshStates":
            type(self).polls += 1
            self._send(
                {
                    "last": type(self).polls,
                    "events": [
                        {
                            "type": "DevicePropertyUpdatedEvent",
                            "data": {
                                "id": 10,
                                "property": "value",
                                "newValue": type(self).polls % 2 == 1,
                            },
                        }
                    ],
                }
            )
        else:
            self._send({}, 404)

    def _send(self, data, status: int = 200) -> None:
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def test_record_captures_devices_and_refresh_events(tmp_path, monkeypatch) -> None:
    _MockHc3.polls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        result = _run(
            "record", "--duration", "1.2", "--interval", "0.3", "-o", "rec.json", cwd=tmp_path
        )
        assert result.returncode == 0, result.stdout + result.stderr
        recording = json.loads((tmp_path / "rec.json").read_text())
        assert recording["meta"]["controller"] == "my-hc3"
        assert [d["id"] for d in recording["devices"]] == [10]
        events = recording["events"]
        assert len(events) >= 3, events  # every poll flips the value
        assert all(e["deviceId"] == 10 and e["property"] == "value" for e in events)
        assert events[0]["newValue"] is True and events[1]["newValue"] is False
        times = [e["t"] for e in events]
        assert times == sorted(times)  # relative times, monotonically increasing
        assert "recorded" in result.stdout
    finally:
        server.shutdown()
        server.server_close()


def _recording(tmp_path: Path) -> Path:
    recording = tmp_path / "house.json"
    recording.write_text(
        json.dumps(
            {
                "version": 1,
                "meta": {"capturedAt": "2026-10-24T00:00:00Z"},
                "devices": [
                    {
                        "id": 10,
                        "name": "lamp",
                        "type": "com.fibaro.binarySwitch",
                        "properties": {"value": False},
                    }
                ],
                "events": [
                    {"t": 0.05, "deviceId": 10, "property": "value", "newValue": True},
                    {"t": 0.15, "deviceId": 10, "property": "value", "newValue": False},
                    # a device the recording knows but this run does not seed:
                    # the replayer skips it silently
                    {"t": 0.2, "deviceId": 99, "property": "value", "newValue": True},
                ],
            }
        )
    )
    return recording


_QA = (
    "--%%name:replay_qa\n"
    "local sub = RefreshStateSubscriber()\n"
    "sub:subscribe(\n"
    "  function(event) return event.data and event.data.id == 10 end,\n"
    "  function(event) print('GOT', tostring(event.data.newValue)) end)\n"
    "sub:run()\n"
    "setTimeout(function() exit(0) end, 500)\n"
)


def test_replay_fires_recorded_events(tmp_path) -> None:
    recording = _recording(tmp_path)
    (tmp_path / "qa.lua").write_text(_QA)
    # the --replay flag...
    result = _run("--replay", str(recording), "qa.lua", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GOT true" in result.stdout and "GOT false" in result.stdout
    # ...and the --%%replay directive form (also reachable via .flua-directives)
    (tmp_path / "qa.lua").write_text(f"--%%replay:{recording}\n" + _QA)
    result = _run("qa.lua", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GOT true" in result.stdout and "GOT false" in result.stdout
    # instant mode replays the whole recording immediately
    result = _run("--instant", "--replay", str(recording), "qa.lua", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GOT true" in result.stdout and "GOT false" in result.stdout


def test_replay_requires_events_list(tmp_path) -> None:
    (tmp_path / "notrec.json").write_text('{"devices": []}\n')
    (tmp_path / "qa.lua").write_text("exit(0)\n")
    result = _run("--replay", "notrec.json", "qa.lua", cwd=tmp_path)
    assert result.returncode != 0
    assert "no events list" in result.stderr
