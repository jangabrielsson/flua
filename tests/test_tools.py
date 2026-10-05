"""The --tool registry: one module per tool, discovered automatically.

Adding a tool means adding a module to flua/tools/ exporting NAME, HELP,
add_arguments() and run() — no other file changes.
"""

import argparse
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua import tools  # noqa: E402


def test_registry_discovers_all_tools() -> None:
    assert tools.tool_names() == [
        "createDB",
        "downloadFQA",
        "downloadQA",
        "newQA",
        "pack",
        "setup",
        "unpack",
        "updateQA",
        "uploadFQA",
        "uploadQA",
    ]
    for name in tools.tool_names():
        module = tools._TOOLS[name]
        assert module.NAME == name
        assert module.HELP
        assert callable(module.add_arguments)
        assert callable(module.run)


def test_unknown_tool_reports_and_exits_2(capsys) -> None:
    assert tools.run_tool("bogus", []) == 2
    err = capsys.readouterr().err
    assert "unknown tool 'bogus'" in err
    assert "downloadQA" in err  # the usage hint lists the known tools


def test_tool_listing(capsys) -> None:
    # "help", a bare name, and the flag spellings all list the installed tools
    for name in ("", "help", "list", "-h", "--help"):
        assert tools.run_tool(name, []) == 0
        out = capsys.readouterr().out
        for tool in tools.tool_names():
            assert tool in out
        assert "flua --tool <name> --help" in out


class _MockHc3(BaseHTTPRequestHandler):
    """Serves the endpoints createDB/uploadFQA/downloadFQA/updateQA read."""

    fqas: dict[int, dict] = {}  # id -> fqa, for the upload/download roundtrip
    devices: dict[int, dict] = {}  # id -> device, for updateQA
    requests: list[tuple[str, str, object]] = []  # (method, path, body)
    next_id: int = 100

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else None

    def _send(self, data, status: int = 200) -> None:
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/settings/location":
            self._send({"latitude": 57.7, "longitude": 11.97})
        elif path == "/api/settings/info":
            self._send({"hcName": "my-hc3", "serialNumber": "HC3-1"})
        elif path == "/api/devices/1":
            self._send(
                {
                    "id": 1,
                    "name": "my-hc3",
                    "type": "HC3",
                    "properties": {"sunriseHour": "06:00", "sunsetHour": "21:30"},
                }
            )
        elif path == "/api/panels/location":
            self._send([{"id": 1, "name": "Home", "latitude": 57.7, "longitude": 11.97}])
        elif path.startswith("/api/devices/") and len(path.split("/")) == 4:
            device = type(self).devices.get(int(path.split("/")[3]))
            self._send(device if device is not None else {}, 200 if device else 404)
        else:
            self._send({}, 404)

    def do_PUT(self):
        path = self.path.split("?")[0]
        body = self._read_body()
        type(self).requests.append(("PUT", path, body))
        if path.startswith("/api/devices/") and len(path.split("/")) == 4:
            device = type(self).devices.get(int(path.split("/")[3]))
            if device is None:
                self._send({}, 404)
                return
            if isinstance(body, dict) and "name" in body:
                device["name"] = body["name"]
            self._send(None, 204)
        elif path.startswith("/api/quickApp/") and path.endswith("/files"):
            self._send(None, 204)
        else:
            self._send({}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/quickApp":
            # the flua client unwraps its own base64 envelope and sends the
            # raw .fqa JSON body (the real HC3 contract)
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8")
            try:
                fqa = json.loads(raw)
            except Exception:
                self._send({}, 400)
                return
            self.fqas[self.next_id] = fqa
            self._send({"id": self.next_id, "name": fqa["name"]})
            self.next_id += 1
        elif path.startswith("/api/quickApp/") and path.endswith("/export"):
            qa_id = int(path.split("/")[3])
            fqa = self.fqas.get(qa_id)
            if fqa is None:
                self._send({}, 404)
            else:
                self._send(fqa)
        elif path == "/api/plugins/updateProperty":
            body = self._read_body()
            type(self).requests.append(("POST", path, body))
            device = type(self).devices.get((body or {}).get("deviceId"))
            if device is not None and isinstance(body, dict):
                device.setdefault("properties", {})[body["propertyName"]] = body["value"]
            self._send(None, 204)
        elif path == "/api/plugins/interfaces":
            body = self._read_body()
            type(self).requests.append(("POST", path, body))
            device = type(self).devices.get((body or {}).get("deviceId"))
            if device is not None and isinstance(body, dict):
                interfaces = set(device.setdefault("interfaces", []))
                if body["action"] == "add":
                    interfaces.update(body["interfaces"])
                else:
                    interfaces.difference_update(body["interfaces"])
                device["interfaces"] = sorted(interfaces)
            self._send(None, 204)
        else:
            self._send({}, 404)

    def log_message(self, *args) -> None:
        pass


def test_pack_unpack_tools_roundtrip(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lib.lua").write_text("function helper() return 'lib' end\n")
    (tmp_path / "main.lua").write_text(
        "--%%name:packed\n"
        "--%%type:com.fibaro.binarySwitch\n"
        "--%%file:lib.lua,lib\n"
        "function QuickApp:onInit() print('HI', helper()) end\n"
    )
    pack = tools._TOOLS["pack"]
    parser = argparse.ArgumentParser()
    pack.add_arguments(parser)
    assert pack.run(parser, parser.parse_args(["main.lua"])) == 0
    assert "packed packed (2 files)" in capsys.readouterr().out
    fqa = json.loads((tmp_path / "main.fqa").read_text())
    assert fqa["name"] == "packed" and len(fqa["files"]) == 2
    # and back out as a project
    unpack = tools._TOOLS["unpack"]
    parser = argparse.ArgumentParser()
    unpack.add_arguments(parser)
    assert unpack.run(parser, parser.parse_args(["main.fqa", "-d", "proj"])) == 0
    assert "unpacked to proj/" in capsys.readouterr().out
    assert "--%%name:packed" in (tmp_path / "proj" / "main.lua").read_text()


def test_upload_and_download_fqa_tools(tmp_path, monkeypatch, capsys) -> None:
    _MockHc3.fqas = {}
    _MockHc3.next_id = 100
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        monkeypatch.chdir(tmp_path)
        (tmp_path / "qa.lua").write_text(
            "--%%name:roundtrip\n"
            "--%%type:com.fibaro.binarySwitch\n"
            "function QuickApp:onInit() end\n"
        )
        pack = tools._TOOLS["pack"]
        parser = argparse.ArgumentParser()
        pack.add_arguments(parser)
        assert pack.run(parser, parser.parse_args(["qa.lua"])) == 0
        upload = tools._TOOLS["uploadFQA"]
        parser = argparse.ArgumentParser()
        upload.add_arguments(parser)
        assert upload.run(parser, parser.parse_args(["qa.fqa"])) == 0
        assert "uploaded roundtrip — HC3 device id 100" in capsys.readouterr().out
        download = tools._TOOLS["downloadFQA"]
        parser = argparse.ArgumentParser()
        download.add_arguments(parser)
        assert download.run(parser, parser.parse_args(["100"])) == 0
        assert "downloaded roundtrip (id 100)" in capsys.readouterr().out
        fqa = json.loads((tmp_path / "roundtrip.fqa").read_text())
        assert fqa["name"] == "roundtrip"
    finally:
        server.shutdown()
        server.server_close()


def test_update_qa_syncs_files_name_properties_and_interfaces(
    tmp_path, monkeypatch, capsys
) -> None:
    # updateQA is no longer files-only: it syncs the package's name, the
    # standard properties (UI structures + description) and the interfaces,
    # each only when it changed — and is idempotent after that
    _MockHc3.requests = []
    _MockHc3.devices = {
        100: {
            "id": 100,
            "name": "oldname",
            "type": "com.fibaro.binarySwitch",
            "properties": {},
            "interfaces": ["quickApp"],
        }
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        monkeypatch.chdir(tmp_path)
        main = tmp_path / "qa_main_100.lua"
        main.write_text(
            "--%%name:newname\n"
            "--%%type:com.fibaro.binarySwitch\n"
            '--%%u:{label="lbl",text="Hi"}\n'
            "--%%description:Updated description\n"
            "function QuickApp:onInit() end\n"
        )
        module = tools._TOOLS["uploadQA"]
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        assert module.run(parser, parser.parse_args(["qa_main_100.lua"])) == 0
        out = capsys.readouterr().out
        assert "updated QA 100 from newname" in out
        # name, properties and interfaces changed; files are always pushed
        puts = [r for r in _MockHc3.requests if r[0] == "PUT" and r[1] == "/api/devices/100"]
        assert puts and puts[-1][2] == {"name": "newname"}
        props = [
            r for r in _MockHc3.requests if r[0] == "POST" and r[1] == "/api/plugins/updateProperty"
        ]
        names = {r[2]["propertyName"] for r in props}
        assert {"viewLayout", "uiView", "uiCallbacks", "useUiView", "userDescription"} <= names
        iface = [
            r for r in _MockHc3.requests if r[0] == "POST" and r[1] == "/api/plugins/interfaces"
        ]
        assert iface and iface[0][2] == {
            "deviceId": 100,
            "action": "add",
            "interfaces": ["autoTurnOff", "light"],
        }
        # idempotent: a second run pushes only the files
        _MockHc3.requests = []
        assert module.run(parser, parser.parse_args(["qa_main_100.lua"])) == 0
        capsys.readouterr()
        assert not [
            r
            for r in _MockHc3.requests
            if r[0] == "POST" or (r[0] == "PUT" and r[1] == "/api/devices/100")
        ]
        assert [r for r in _MockHc3.requests if r[0] == "PUT" and r[1] == "/api/quickApp/100/files"]
    finally:
        server.shutdown()
        server.server_close()


def test_create_db_tool(tmp_path, monkeypatch, capsys) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        parser = argparse.ArgumentParser()
        module = tools._TOOLS["createDB"]
        module.add_arguments(parser)
        out = tmp_path / "db.json"
        assert module.run(parser, parser.parse_args(["-o", str(out)])) == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["location"] == {"latitude": 57.7, "longitude": 11.97}
        assert doc["devices"][0]["name"] == "my-hc3"
        assert doc["devices"][0]["properties"]["sunsetHour"] == "21:30"
        assert doc["familyLocations"][0]["name"] == "Home"
        # an existing file is protected unless --force
        with pytest.raises(SystemExit):
            module.run(parser, parser.parse_args(["-o", str(out)]))
        assert "exists" in capsys.readouterr().err
    finally:
        server.shutdown()


def test_family_locations_seed_and_serve(tmp_path) -> None:
    from flua.api import Api

    api = Api(seed={"familyLocations": [{"id": 1, "name": "Sommarstuga"}]})
    data, status = api.dispatch("GET", "/panels/location")
    assert status == 200 and data[0]["name"] == "Sommarstuga"


def test_new_qa_tool_scaffolds_from_templates(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    module = tools._TOOLS["newQA"]
    parser = argparse.ArgumentParser()
    module.add_arguments(parser)
    # no type: lists all templates
    assert module.run(parser, parser.parse_args([])) == 0
    out = capsys.readouterr().out
    assert "binarySwitch" in out and "motionSensor" in out
    # scaffold with a name: the --%%name is substituted, the type kept
    assert module.run(parser, parser.parse_args(["binarySwitch", "Hall lamp"])) == 0
    out = capsys.readouterr().out
    assert "wrote binarySwitch.lua" in out
    source = (tmp_path / "binarySwitch.lua").read_text()
    assert "--%%name:Hall lamp" in source
    assert "--%%type:com.fibaro.binarySwitch" in source
    # an existing file is kept unless --force
    assert module.run(parser, parser.parse_args(["binarySwitch", "x"])) == 1
    assert "exists" in capsys.readouterr().err
    assert module.run(parser, parser.parse_args(["-f", "binarySwitch", "x"])) == 0
    # unknown and ambiguous types are reported, not guessed
    assert module.run(parser, parser.parse_args(["bogus"])) == 1
    assert "unknown" in capsys.readouterr().err
    assert module.run(parser, parser.parse_args(["sensor"])) == 1
    assert "ambiguous" in capsys.readouterr().err


def test_setup_tool_scaffolds_a_qa_project(tmp_path, capsys) -> None:
    module = tools._TOOLS["setup"]
    parser = argparse.ArgumentParser()
    module.add_arguments(parser)
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    out = capsys.readouterr().out
    # the VS Code configs and the agent files land (the viewer is NOT copied
    # — flua --ui serves it from the package)
    for path in (
        ".vscode/launch.json",
        ".vscode/extensions.json",
        ".luarc.json",
        "AGENTS.md",
        ".github/copilot-instructions.md",
        ".github/instructions/quickapp-dev.instructions.md",
        ".github/prompts/install-qa-skills.prompt.md",
        ".github/skills/quickapp-api/SKILL.md",
    ):
        assert (tmp_path / path).exists(), path
    assert "wrote .vscode/launch.json" in out
    # the reading links (clickable in the VS Code terminal)
    assert "github.com/jangabrielsson/flua/blob/main/USAGE.md" in out
    assert "github.com/jangabrielsson/flua/tree/main/docs/tutorial" in out
    # the launch configs: run (panel/terminal/UI), debug (mobdebug, and
    # mobdebug with the UI viewer) — no --api flag anywhere, so the QA's own
    # --%%mode directive decides (the default is the offline sim)
    launch = (tmp_path / ".vscode/launch.json").read_text()
    assert "Flua: Run Current File (UI)" in launch
    assert "Flua: Debug Current File (UI+mobdebug)" in launch
    assert "--api" not in launch
    configs = json.loads(launch)["configurations"]
    interpreters = [c["interpreter"] for c in configs if "interpreter" in c]
    # absolute paths on all platforms: .../bin/flua on POSIX, flua.exe on
    # Windows (shutil.which resolves the console script via PATHEXT there)
    assert interpreters and all(
        i.endswith(("flua", "flua.exe")) and i != "flua" for i in interpreters
    )
    # the mermaid extension recommendation renders docs/tutorial diagrams in
    # VS Code's markdown preview
    extensions = (tmp_path / ".vscode/extensions.json").read_text()
    assert "bierner.markdown-mermaid" in extensions
    # idempotent: a second run keeps the existing files
    (tmp_path / "AGENTS.md").write_text("custom\n")
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    assert "kept AGENTS.md" in capsys.readouterr().out
    assert (tmp_path / "AGENTS.md").read_text() == "custom\n"
    # --force overwrites
    assert module.run(parser, parser.parse_args(["--force", str(tmp_path)])) == 0
    assert "flua" in (tmp_path / "AGENTS.md").read_text()


def test_setup_falls_back_to_bare_flua_when_not_on_path(
    tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    module = tools._TOOLS["setup"]
    parser = argparse.ArgumentParser()
    module.add_arguments(parser)
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    out = capsys.readouterr().out
    assert "flua not found on PATH" in out
    launch = json.loads((tmp_path / ".vscode/launch.json").read_text())
    interpreters = [c["interpreter"] for c in launch["configurations"] if "interpreter" in c]
    assert interpreters and all(i == "flua" for i in interpreters)


def test_setup_reports_missing_templates_cleanly(tmp_path, capsys, monkeypatch) -> None:
    # a wheel packaging gap (e.g. a template the globs dropped) must be a
    # clear error, not a half-scaffolded project + FileNotFoundError
    module = tools._TOOLS["setup"]
    empty = tmp_path / "templates"
    empty.mkdir()
    monkeypatch.setattr(module, "_templates_dir", lambda: empty)
    parser = argparse.ArgumentParser()
    module.add_arguments(parser)
    with pytest.raises(SystemExit) as exc:
        module.run(parser, parser.parse_args([str(tmp_path / "proj")]))
    assert exc.value.code == 2  # parser.error
    err = capsys.readouterr().err
    assert "missing packaged templates" in err
    assert "reinstall fibaro-flua" in err
    assert not list((tmp_path / "proj").iterdir())  # nothing half-written


def test_packaged_skills_match_the_repo() -> None:
    # the wheel ships the skills; a sync guard keeps the copies honest
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "github" / "skills"
    for origin in (repo / ".github" / "skills").rglob("*"):
        if origin.is_file():
            copy = packaged / origin.relative_to(repo / ".github" / "skills")
            assert copy.exists(), f"missing packaged skill: {copy}"
            assert copy.read_bytes() == origin.read_bytes(), f"drifted: {copy}"


def test_sync_skills_script_restores_drift() -> None:
    # scripts/sync-skills.sh is the manual way back in sync: run it after a
    # deliberate drift and the packaged copies match the repo again
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "github" / "skills"
    victim = packaged / "quickapp-types" / "SKILL.md"
    original = victim.read_bytes()
    victim.write_bytes(original + b"\n<!-- drift -->\n")
    try:
        result = subprocess.run(
            [str(repo / "scripts" / "sync-skills.sh")],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
    finally:
        if victim.read_bytes() != original:
            victim.write_bytes(original)  # never leave the tree drifted
    assert victim.read_bytes() == original
    assert "synced .github/skills" in result.stdout


def test_packaged_viewer_matches_the_repo() -> None:
    # the wheel ships the UI viewer for --tool setup; a sync guard keeps the
    # packaged copy identical to the repo's viewer/index.html
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "viewer" / "index.html"
    origin = repo / "viewer" / "index.html"
    assert packaged.read_bytes() == origin.read_bytes(), (
        "viewer drift — copy viewer/index.html into setup_templates/viewer/"
    )


def test_sanitize_filename() -> None:
    from flua.engine import sanitize_filename

    assert sanitize_filename("My QA!") == "My_QA"
    assert sanitize_filename("compiler-qa.v2") == "compiler_qa_v2"
    assert sanitize_filename("  ") == "qa"  # nothing usable left -> "qa"
