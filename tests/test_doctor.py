"""flua doctor: the one-command environment health check (src/flua/doctor.py)."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(*argv: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "flua", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


class _MockHc3(BaseHTTPRequestHandler):
    """Serves /api/settings/info; the status class var selects the reply."""

    status: int = 200

    def do_GET(self):
        if self.path.startswith("/api/settings/info"):
            if type(self).status == 200:
                self._send({"hcName": "my-hc3", "softVersion": "5.210.12"})
            else:
                self._send({}, type(self).status)
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


def _mock_hc3(status: int = 200) -> tuple[ThreadingHTTPServer, threading.Thread]:
    _MockHc3.status = status
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    return server, thread


def _fake_home(tmp_path: Path, with_extension: bool = False) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    if with_extension:
        (home / ".vscode" / "extensions" / "gsonsoft-development.flua-0.1.83").mkdir(parents=True)


def _full_project(tmp_path: Path) -> None:
    (tmp_path / ".luarc.json").write_text("{}\n")
    (tmp_path / ".luals").mkdir()
    (tmp_path / ".vscode").mkdir()
    (tmp_path / ".vscode" / "launch.json").write_text("{}\n")


def test_doctor_reports_missing_project_setup(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    result = _run("doctor", cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "LuaLS setup" in result.stdout and "flua --tool setup" in result.stdout
    assert "no .vscode/launch.json" in result.stdout
    assert "offline sim only" in result.stdout  # no credentials = legitimate offline use
    assert "problem(s)" in result.stdout
    # the JSON form is machine-readable and agrees with the exit code
    result = _run("doctor", "--json", cwd=tmp_path)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    names = [check["name"] for check in payload["checks"]]
    assert "LuaLS setup" in names and "HC3 connection" in names


def test_doctor_all_ok_with_mock_hc3(tmp_path, monkeypatch) -> None:
    server, thread = _mock_hc3()
    try:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        _fake_home(tmp_path, with_extension=True)
        _full_project(tmp_path)
        (tmp_path / ".env").write_text(
            f"HC3_URL=http://127.0.0.1:{server.server_port}\n"
            "HC3_USER=admin\nHC3_PASSWORD=secret\n"
        )
        result = _run("doctor", cwd=tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "HC3_URL set" in result.stdout
        assert "my-hc3" in result.stdout and "5.210.12" in result.stdout
        assert "installed (version 0.1.83)" in result.stdout
        assert "0 problem(s)" in result.stdout
    finally:
        server.shutdown()
        server.server_close()


def test_doctor_bad_credentials_and_partial_env(tmp_path, monkeypatch) -> None:
    server, thread = _mock_hc3(status=401)
    try:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        (tmp_path / ".env").write_text(
            f"HC3_URL=http://127.0.0.1:{server.server_port}\n"
            "HC3_USER=admin\nHC3_PASSWORD=wrong\n"
        )
        result = _run("doctor", cwd=tmp_path)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "credentials rejected" in result.stdout
        # half-configured credentials are a problem, not silent — scrub the
        # parent environment's HC3_* exports so only the .env file counts
        scrubbed = dict(__import__("os").environ)
        for key in ("HC3_USER", "HC3_PASSWORD", "HC3_URL"):
            scrubbed.pop(key, None)  # remove, not empty: set-but-empty would shadow .env
        (tmp_path / ".env").write_text(f"HC3_URL=http://127.0.0.1:{server.server_port}\n")
        result = _run("doctor", "--no-network", cwd=tmp_path, env=scrubbed)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "partially configured" in result.stdout
        assert "missing HC3_PASSWORD, HC3_USER" in result.stdout
    finally:
        server.shutdown()
        server.server_close()


def test_doctor_no_network_skips_connection(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _fake_home(tmp_path, with_extension=True)
    _full_project(tmp_path)
    (tmp_path / ".env").write_text(
        "HC3_URL=http://127.0.0.1:1\nHC3_USER=admin\nHC3_PASSWORD=secret\n"
    )
    result = _run("doctor", "--no-network", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "skipped (--no-network)" in result.stdout
