"""flua --tool hubList: hub info + QuickApp list as one JSON document."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

HUB_INFO = {
    "hcName": "HC3-00000422",
    "serialNumber": "HC3-00000422",
    "model": "HC3",
    "softVersion": "5.221.22",
}
ROOMS = [
    {"id": 1, "name": "Kitchen"},
    {"id": 2, "name": "Living room"},
]
DEVICES = [
    {
        "id": 57,
        "name": "Heating",
        "type": "com.fibaro.deviceController",
        "roomID": 2,
        "interfaces": ["quickApp", "power"],
    },
    {
        "id": 12,
        "name": "Ceiling lamp",
        "type": "com.fibaro.binarySwitch",
        "roomID": 1,
        "interfaces": ["light", "zwave"],
    },
    {
        "id": 58,
        "name": "Alarm",
        "type": "com.fibaro.alarm",
        "roomID": None,
        "interfaces": ["quickApp"],
    },
]


class _MockHub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/settings/info":
            body = HUB_INFO
        elif path == "/api/rooms":
            body = ROOMS
        elif path == "/api/devices":
            body = DEVICES
        else:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence request logs
        pass


def _fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return home


def _scrubbed() -> dict[str, str]:
    # the parent shell may export HC3_* — the .env file under test must win
    env = os.environ.copy()
    for key in ("HC3_URL", "HC3_HOST", "HC3_USER", "HC3_PASSWORD"):
        env.pop(key, None)
    return env


def _run(*argv: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "hubList", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env if env is not None else _scrubbed(),
    )


def test_hub_list_reports_hub_and_qas(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(_fake_home(tmp_path)))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHub)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        (tmp_path / ".env").write_text(
            f"HC3_URL={url}\nHC3_USER=admin\nHC3_PASSWORD=secret\n"
        )
        result = _run(cwd=tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        hub = payload["hub"]
        assert hub["url"] == url
        assert hub["reachable"] is True
        assert hub["name"] == "HC3-00000422"
        assert hub["model"] == "HC3"
        assert hub["firmware"] == "5.221.22"
        qas = payload["qas"]
        assert [qa["id"] for qa in qas] == [57, 58]  # the binarySwitch is filtered out
        assert qas[0]["name"] == "Heating"
        assert qas[0]["type"] == "com.fibaro.deviceController"
        assert qas[0]["room"] == "Living room"  # roomID resolved to its name
        assert qas[1]["room"] is None
    finally:
        server.shutdown()
        server.server_close()


def test_hub_list_requires_hc3_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(_fake_home(tmp_path)))
    result = _run(cwd=tmp_path)
    assert result.returncode == 2
    assert "HC3_URL" in result.stderr
    assert result.stdout == ""


def test_hub_list_unreachable_hub_reports_and_exits_1(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(_fake_home(tmp_path)))
    (tmp_path / ".env").write_text(
        "HC3_URL=http://127.0.0.1:1\nHC3_USER=admin\nHC3_PASSWORD=secret\n"
    )
    result = _run(cwd=tmp_path)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["hub"]["reachable"] is False
    assert "error" in payload["hub"]
    assert payload["qas"] == []
