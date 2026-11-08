"""flua --tool hub: named HC3 profiles and .env-chain switching."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class _MockHub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/settings/info"):
            payload = json.dumps({"hcName": "HC3-00000422"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def _scrubbed() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HC3_URL", "HC3_HOST", "HC3_USER", "HC3_PASSWORD"):
        env.pop(key, None)
    return env


def _run(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "hub", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env=_scrubbed(),
    )


def _fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    return home


def _serve(tmp_path: Path) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHub)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _profiles(home: Path) -> dict:
    return json.loads((home / ".flua" / "hubs.json").read_text())


def test_hub_add_captures_serial_and_list_hides_passwords(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLUA_HUB_PASSWORD", "secretpw")
    home = _fake_home(tmp_path, monkeypatch)
    server, url = _serve(tmp_path)
    try:
        result = _run("add", "home", url, "admin", cwd=tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "HC3-00000422" in result.stdout  # the serial came from the hub
        # the profile stores the password, the file is private
        profiles = _profiles(home)
        assert profiles["home"]["password"] == "secretpw"
        mode = stat.S_IMODE((home / ".flua" / "hubs.json").stat().st_mode)
        assert mode == 0o600
        # list --json: never the password (the extension/agent contract)
        result = _run("list", "--json", cwd=tmp_path)
        assert result.returncode == 0
        public = json.loads(result.stdout)
        assert public["home"]["url"] == url
        assert public["home"]["serial"] == "HC3-00000422"
        assert public["home"]["active"] is False  # nothing in the chain yet
        assert "password" not in public["home"]
        # human list masks it too
        result = _run("list", cwd=tmp_path)
        assert "secretpw" not in result.stdout
        assert "HC3-00000422" in result.stdout
        # after a switch, the matching profile is marked active
        assert _run("switch", "home", cwd=tmp_path).returncode == 0
        active = json.loads(_run("list", "--json", cwd=tmp_path).stdout)
        assert active["home"]["active"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_hub_add_duplicate_needs_force(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLUA_HUB_PASSWORD", "pw")
    home = _fake_home(tmp_path, monkeypatch)
    result = _run("add", "home", "http://127.0.0.1:1", "admin", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    result = _run("add", "home", "http://127.0.0.1:1", "admin", cwd=tmp_path)
    assert result.returncode == 2
    assert "exists" in result.stderr
    result = _run("add", "home", "http://127.0.0.1:1", "admin", "-f", cwd=tmp_path)
    assert result.returncode == 0
    assert _profiles(home)["home"]["password"] == "pw"  # -f replaced the entry


def test_hub_switch_rewrites_home_env_preserving_other_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLUA_HUB_PASSWORD", "pw")
    home = _fake_home(tmp_path, monkeypatch)
    (home / ".env").write_text(
        "HC3_URL=http://old\nHC3_USER=olduser\nHC3_PASSWORD=oldpw\nOTHER_KEY=keep me\n"
    )
    assert _run("add", "cottage", "http://192.168.2.30", "admin", cwd=tmp_path).returncode == 0
    result = _run("switch", "cottage", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    text = (home / ".env").read_text()
    assert "HC3_URL=http://192.168.2.30" in text
    assert "HC3_PASSWORD=pw" in text
    assert "OTHER_KEY=keep me" in text
    assert "http://old" not in text


def test_hub_switch_project_writes_cwd_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLUA_HUB_PASSWORD", "pw")
    home = _fake_home(tmp_path, monkeypatch)
    assert _run("add", "home", "http://192.168.1.20", "admin", cwd=tmp_path).returncode == 0
    result = _run("switch", "home", "--project", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "HC3_URL=http://192.168.1.20" in (tmp_path / ".env").read_text()
    assert not (home / ".env").exists()  # the global default is untouched


def test_hub_switch_unknown_name_errors(tmp_path, monkeypatch) -> None:
    _fake_home(tmp_path, monkeypatch)
    result = _run("switch", "nope", cwd=tmp_path)
    assert result.returncode == 2
    assert "unknown hub" in result.stderr


def test_hub_remove_deletes_the_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLUA_HUB_PASSWORD", "pw")
    home = _fake_home(tmp_path, monkeypatch)
    assert _run("add", "home", "http://127.0.0.1:1", "admin", cwd=tmp_path).returncode == 0
    result = _run("remove", "home", cwd=tmp_path)
    assert result.returncode == 0
    assert "home" not in _profiles(home)
    result = _run("remove", "home", cwd=tmp_path)
    assert result.returncode == 2
