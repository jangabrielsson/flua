"""The --tool registry: one module per tool, discovered automatically.

Adding a tool means adding a module to flua/tools/ exporting NAME, HELP,
add_arguments() and run() — no other file changes.
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua import tools  # noqa: E402


def test_registry_discovers_all_tools() -> None:
    assert tools.tool_names() == [
        "createDB",
        "downloadQA",
        "newQA",
        "setup",
        "updateQA",
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
    """Serves the endpoints createDB reads."""

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
        else:
            self._send({}, 404)

    def log_message(self, *args) -> None:
        pass


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
    # the VS Code configs, the viewer, and the agent files land
    for path in (
        ".vscode/launch.json",
        ".vscode/extensions.json",
        "viewer/index.html",
        ".luarc.json",
        "AGENTS.md",
        ".github/copilot-instructions.md",
        ".github/instructions/quickapp-dev.instructions.md",
        ".github/prompts/install-qa-skills.prompt.md",
        ".github/skills/quickapp-api/SKILL.md",
    ):
        assert (tmp_path / path).exists(), path
    assert "wrote viewer/index.html" in out
    assert "wrote .vscode/launch.json" in out
    # the reading links (clickable in the VS Code terminal)
    assert "github.com/jangabrielsson/flua/blob/main/USAGE.md" in out
    assert "github.com/jangabrielsson/flua/tree/main/docs/tutorial" in out
    # the launch configs: run (panel/terminal/UI), debug (mobdebug, and
    # mobdebug with the UI viewer) — all offline, all using the `flua`
    # command (pip users have no .venv)
    launch = (tmp_path / ".vscode/launch.json").read_text()
    assert "Flua: Run Current File (UI)" in launch
    assert "Flua: Debug Current File (UI+mobdebug)" in launch
    assert '"interpreter": "flua"' in launch
    assert '"--api", "local"' in launch
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


def test_packaged_skills_match_the_repo() -> None:
    # the wheel ships the skills; a sync guard keeps the copies honest
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "github" / "skills"
    for origin in (repo / ".github" / "skills").rglob("*"):
        if origin.is_file():
            copy = packaged / origin.relative_to(repo / ".github" / "skills")
            assert copy.exists(), f"missing packaged skill: {copy}"
            assert copy.read_bytes() == origin.read_bytes(), f"drifted: {copy}"


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
