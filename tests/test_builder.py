"""The QA builder (flua --tool build): the recipe index, the param baking,
the HC3 pickers, and the page."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("lupa")

REPO = Path(__file__).resolve().parent.parent


def _serve(monkeypatch, port: int = 0):
    from flua.tools.build import serve_builder

    monkeypatch.delenv("HC3_URL", raising=False)  # offline: typed-id pickers
    server = serve_builder(port)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _post(base: str, path: str, payload: dict) -> tuple[int, dict | bytes]:
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    response = urllib.request.urlopen(request, timeout=10)
    body = response.read()
    return response.status, body


def test_builder_serves_the_page_and_index(monkeypatch) -> None:
    server, base = _serve(monkeypatch)
    try:
        page = urllib.request.urlopen(f"{base}/", timeout=10).read()
        assert b"QA Builder" in page
        assert b'id="cats"' in page  # the category selector above the templates
        index = json.loads(urllib.request.urlopen(f"{base}/api/index", timeout=10).read())
        ids = [recipe["id"] for recipe in index["recipes"]]
        assert len(ids) == 5
        assert "light-at-sunset" in ids
    finally:
        server.shutdown()
        server.server_close()


def test_builder_bakes_picked_params(monkeypatch, tmp_path) -> None:
    server, base = _serve(monkeypatch)
    try:
        status, body = _post(
            base,
            "/api/generate",
            {"id": "light-at-sunset", "params": {"deviceId": 123, "offset": -15}},
        )
        assert status == 200
        code = json.loads(body)["code"]
        assert "--%%var:deviceId=123" in code
        assert "--%%var:offset=-15" in code
        assert "--%%var:deviceId=0" not in code
        # the generated QA is valid flua
        generated = tmp_path / "generated.lua"
        generated.write_text(code, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "flua", "--check", str(generated)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()


def test_builder_quotes_text_params(monkeypatch, tmp_path) -> None:
    server, base = _serve(monkeypatch)
    try:
        status, body = _post(
            base,
            "/api/generate",
            {
                "id": "notify-when-door-opens",
                "params": {"doorId": 9, "message": 'Hej "du" \\ back'},
            },
        )
        assert status == 200
        code = json.loads(body)["code"]
        assert '--%%var:message="Hej \\"du\\" \\\\ back"' in code
        generated = tmp_path / "generated.lua"
        generated.write_text(code, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "flua", "--check", str(generated)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()


def test_builder_downloads_the_generated_file(monkeypatch) -> None:
    server, base = _serve(monkeypatch)
    try:
        status, body = _post(
            base,
            "/api/download",
            {"id": "motion-lights", "params": {"motionId": 7, "lightId": 8, "minutes": 2}},
        )
        assert status == 200
        assert isinstance(body, bytes) and b"--%%var:motionId=7" in body
    finally:
        server.shutdown()
        server.server_close()


def test_builder_proxies_the_hc3_pickers(monkeypatch) -> None:
    class _Hc3(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/devices":
                self._send([{"id": 4, "name": "Lamp", "type": "com.fibaro.binarySwitch"}])
            elif self.path == "/api/rooms":
                self._send([{"id": 1, "name": "Living room"}])
            elif self.path == "/api/scenes":
                self._send([{"id": 2, "name": "Evening"}])
            else:
                self.send_response(404)
                self.end_headers()

        def _send(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    hc3 = ThreadingHTTPServer(("127.0.0.1", 0), _Hc3)
    threading.Thread(target=hc3.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{hc3.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        from flua.tools.build import serve_builder

        server = serve_builder(0)
        threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            data = json.loads(urllib.request.urlopen(f"{base}/api/devices", timeout=10).read())
            assert data["items"] == [{"id": 4, "name": "Lamp", "type": "com.fibaro.binarySwitch"}]
            rooms = json.loads(urllib.request.urlopen(f"{base}/api/rooms", timeout=10).read())
            assert rooms["items"][0]["name"] == "Living room"
        finally:
            server.shutdown()
            server.server_close()
    finally:
        hc3.shutdown()
        hc3.server_close()


def test_builder_uploads_the_generated_qa(monkeypatch) -> None:
    # /api/upload builds the edited code and posts it through the import
    # endpoint (package-preserving) — the HC3 sees the baked values
    seen: list[bytes] = []

    class _Hc3(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            seen.append(self.rfile.read(length))
            body = b'{"id": 555, "name": "Light at sunset"}'
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    hc3 = ThreadingHTTPServer(("127.0.0.1", 0), _Hc3)
    threading.Thread(target=hc3.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{hc3.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        from flua.tools.build import serve_builder

        server = serve_builder(0)
        threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            generated = json.loads(
                _post(
                    base,
                    "/api/generate",
                    {"id": "motion-lights", "params": {"motionId": 7, "lightId": 8, "minutes": 2}},
                )[1]
            )["code"]
            status, body = _post(base, "/api/upload", {"code": generated})
            assert status == 200
            assert json.loads(body)["device"]["id"] == 555
            assert seen, "the HC3 never received the import"
            multipart = seen[0]
            assert b"--%%var:motionId=7" in multipart  # the baked values traveled
            assert b'name="file"' in multipart
        finally:
            server.shutdown()
            server.server_close()
    finally:
        hc3.shutdown()
        hc3.server_close()


def test_builder_passes_istypeof_filters_through(monkeypatch) -> None:
    seen_paths: list[str] = []

    class _Hc3(BaseHTTPRequestHandler):
        def do_GET(self):
            seen_paths.append(self.path)
            body = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    hc3 = ThreadingHTTPServer(("127.0.0.1", 0), _Hc3)
    threading.Thread(target=hc3.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{hc3.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        from flua.tools.build import serve_builder

        server = serve_builder(0)
        threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            urllib.request.urlopen(
                f"{base}/api/devices?isTypeOf=com.fibaro.binarySwitch", timeout=10
            ).read()
            assert seen_paths == ["/api/devices?isTypeOf=com.fibaro.binarySwitch"]
        finally:
            server.shutdown()
            server.server_close()
    finally:
        hc3.shutdown()
        hc3.server_close()


def test_builder_refresh_overwrites_a_stale_cache(monkeypatch, tmp_path) -> None:
    # a refresh must replace cached recipe code, or a bug fixed upstream
    # keeps being served forever from ~/.flua/recipes (cache-first trap)
    from flua.tools import build

    monkeypatch.setattr(build, "_CACHE_ROOT", tmp_path)
    versions = iter(
        [
            (200, '{"recipes":[{"id":"light-at-sunset","name":"Light at sunset"}]}'),
            (200, "--%%var:deviceId=0"),
            (200, '{"recipes":[{"id":"light-at-sunset","name":"Light at sunset"}]}'),
            (200, "--%%var:deviceId=42"),
        ]
    )

    monkeypatch.setattr(build, "_fetch", lambda url, timeout=15.0: next(versions))
    build.refresh_recipes()
    assert "--%%var:deviceId=0" in build._recipe_code("light-at-sunset")
    build.refresh_recipes()  # upstream fixed the recipe
    assert "--%%var:deviceId=42" in build._recipe_code("light-at-sunset")


def test_builder_index_prefers_the_cache_without_refresh(monkeypatch, tmp_path) -> None:
    # a plain /api/index serves the last refreshed index (possibly newer
    # than the shipped snapshot) and stays fully offline otherwise
    from flua.tools import build

    monkeypatch.setattr(build, "_CACHE_ROOT", tmp_path)
    assert build.cached_index() == build.shipped_index()  # nothing cached yet

    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "index.json").write_text(
        '{"recipes":[{"id":"brand-new-recipe"}]}', encoding="utf-8"
    )
    cached = build.cached_index()
    assert [r["id"] for r in cached["recipes"]] == ["brand-new-recipe"]


def test_builder_simulates_the_generated_qa(monkeypatch) -> None:
    # simulate runs the generated code in the offline sim (no HC3): the QA
    # boots, prints its hint for unset params, and reports no errors
    server, base = _serve(monkeypatch)
    try:
        generated = json.loads(
            _post(
                base,
                "/api/generate",
                {"id": "light-at-sunset", "params": {"deviceId": 0, "offset": -15}},
            )[1]
        )["code"]
        status, body = _post(
            base,
            "/api/simulate",
            {"id": "light-at-sunset", "code": generated, "minutes": 1},
        )
        assert status == 200
        result = json.loads(body)
        assert result["error"] is None
        assert result["devices"] == []
        assert result["qa"]["id"] == 5000
        assert "set deviceId (the light's id) and restart" in result["log"]
    finally:
        server.shutdown()
        server.server_close()


def test_builder_simulate_seeds_sim_devices(monkeypatch) -> None:
    # a picked device id is re-pointed at a bundled sim device of the same
    # kind, so the QA polls a real sim world (the sim device logs its boot)
    server, base = _serve(monkeypatch)
    try:
        generated = json.loads(
            _post(
                base,
                "/api/generate",
                {"id": "light-at-sunset", "params": {"deviceId": 999, "offset": -15}},
            )[1]
        )["code"]
        status, body = _post(
            base,
            "/api/simulate",
            {"id": "light-at-sunset", "code": generated, "minutes": 1},
        )
        assert status == 200
        result = json.loads(body)
        assert result["error"] is None
        assert result["devices"] == [{"name": "deviceId", "kind": "binarySwitch", "simId": 5000}]
        assert result["qa"]["id"] == 5001
        assert "sim device ready, id 5000" in result["log"]
    finally:
        server.shutdown()
        server.server_close()


def test_builder_serves_the_qa_web_view(monkeypatch) -> None:
    # View UI boots the generated code on a persistent engine and serves
    # the HC3-style viewer; the seeded sim devices are listed in the world
    server, base = _serve(monkeypatch)
    try:
        generated = json.loads(
            _post(
                base,
                "/api/generate",
                {"id": "leak-alert", "params": {"floodId": 9, "sirenId": 8}},
            )[1]
        )["code"]
        status, body = _post(base, "/api/viewui", {"id": "leak-alert", "code": generated})
        assert status == 200
        data = json.loads(body)
        assert data["url"].startswith("http://127.0.0.1:")
        assert data["devices"] == [
            {"name": "floodId", "kind": "binarySensor", "simId": 5000},
            {"name": "sirenId", "kind": "binarySwitch", "simId": 5001},
        ]
        page = urllib.request.urlopen(data["url"], timeout=10).read()
        assert b"<html" in page  # the viewer page serves
        devices = json.loads(
            urllib.request.urlopen(data["url"] + "devices", timeout=10).read()
        )
        ids = [device["id"] for device in devices]
        assert 5000 in ids and 5001 in ids  # the sim world is live
    finally:
        server.shutdown()
        server.server_close()  # also stops the UI session
