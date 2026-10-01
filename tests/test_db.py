"""--%%db: seeding + persistence of emulator state (offline/online)."""

import asyncio
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua.config import parse_annotations  # noqa: E402
from flua.engine import LuaEngine  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


async def wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.01)


def test_db_directive_parsing() -> None:
    cfg = parse_annotations("--%%db:house.json\nprint('hi')\n")
    assert cfg["db"] == {"path": "house.json", "persist": False}
    cfg = parse_annotations("--%%db:+house.json\nprint('hi')\n")
    assert cfg["db"] == {"path": "house.json", "persist": True}
    cfg = parse_annotations("--%%location:latitude=59.33,longitude=18.07\nprint('hi')\n")
    assert cfg["location"] == {"latitude": 59.33, "longitude": 18.07}


def test_db_requires_an_existing_file() -> None:
    with pytest.raises(ValueError, match="cannot read"):
        LuaEngine(db_path="/nonexistent/such/db.json")


@pytest.mark.asyncio
async def test_db_offline_persists_and_restores(tmp_path, capsys) -> None:
    db = tmp_path / "house.json"
    db.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "id": 10,
                        "name": "Lamp",
                        "type": "com.fibaro.binarySwitch",
                        "properties": {"value": False},
                    }
                ],
                "globalVariables": {"nightMode": {"value": "false"}},
            }
        )
    )
    script = tmp_path / "sleepy.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  local kids = api.get('/devices?parentId='..self.id)\n"
        "  print('KIDS', #kids)\n"
        "  if #kids == 0 then\n"
        "    local c = self:createChildDevice({name='c1', type='com.fibaro.binarySwitch'})\n"
        "    print('CREATED', c.id)\n"
        "  end\n"
        "  api.put('/globalVariables/nightMode', {value='true'})\n"
        "  self:updateProperty('value', true)\n"
        "  print('VALUE', self.properties.value)\n"
        "end\n"
    )

    # run 1: creates the child, sets the global variable and a property
    engine = LuaEngine(db_path=str(db), db_persist=True)
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "KIDS 0" in out and "CREATED" in out

    saved = json.loads(db.read_text(encoding="utf-8"))
    assert saved["globalVariables"]["nightMode"]["value"] == "true"
    # the QA shell is not a persisted device; the child lives in qaState
    assert sorted(d["id"] for d in saved["devices"]) == [1, 10]  # the HC3 + the seed
    qa_state = saved["qaState"]["sleepy"]
    assert qa_state["properties"]["value"] is True
    assert len(qa_state["children"]) == 1
    child_id = qa_state["children"][0]["id"]
    assert child_id >= 900000

    # run 2: the child and the QA state come back from the db
    engine = LuaEngine(db_path=str(db), db_persist=True)
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "KIDS 1" in out  # the persisted child was found at startup
    assert "CREATED" not in out  # so it was not created again
    assert "VALUE true" in out  # the persisted property came back


def test_cli_db_directive_persists(tmp_path) -> None:
    # the full path: --%%db:+ in the QA header → the CLI seeds and persists
    db = tmp_path / "house.json"
    db.write_text(json.dumps({"devices": [], "globalVariables": {"n": {"value": "0"}}}))
    script = tmp_path / "a.lua"
    script.write_text(
        f"--%%db:+{db}\n"
        "function QuickApp:onInit()\n"
        "  api.put('/globalVariables/n', {value='7'})\n"
        "end\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--api", "local", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    saved = json.loads(db.read_text(encoding="utf-8"))
    assert saved["globalVariables"]["n"]["value"] == "7"
    assert saved["qaState"]["a"]["properties"]  # the QA's state was recorded


class _MiniHc3(BaseHTTPRequestHandler):
    """Minimal online-mode HC3: an idle refreshStates feed, nothing else."""

    def _send(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith("/api/refreshStates"):
            self._send({"status": "IDLE", "last": 0, "events": [], "changes": []})
            return
        self._send({}, 404)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def mini_hc3():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MiniHc3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.mark.asyncio
async def test_db_online_persists_only_emulator_state(
    tmp_path, capsys, mini_hc3, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", mini_hc3)
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    db = tmp_path / "house.json"
    db.write_text(
        json.dumps(
            {
                "devices": [
                    {"id": 10, "name": "Lamp", "type": "com.fibaro.binarySwitch"}
                ],
                "globalVariables": {"nightMode": {"value": "false"}},
            }
        )
    )
    script = tmp_path / "a.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  api.put('/globalVariables/nightMode', {value='true'})\n"
        "  self:updateProperty('value', true)\n"
        "  self:internalStorageSet('token', 'abc')\n"
        "end\n"
    )
    engine = LuaEngine(api_mode="remote", db_path=str(db), db_persist=True)
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(0.4)
    finally:
        await engine.stop()

    saved = json.loads(db.read_text(encoding="utf-8"))
    # the real HC3 owns the house data: only emulator artifacts persist
    assert set(saved.keys()) == {"version", "globalVariables", "qaState"}
    assert saved["globalVariables"]["nightMode"]["value"] == "true"
    qa = saved["qaState"]["a"]
    assert qa["properties"]["value"] is True
    assert qa["variables"]["token"]["value"] == "abc"


@pytest.mark.asyncio
async def test_db_persists_internal_storage(tmp_path, capsys) -> None:
    db = tmp_path / "house.json"
    db.write_text(json.dumps({"globalVariables": {}}))
    script = tmp_path / "store.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  local v = self:internalStorageGet('token')\n"
        "  print('TOKEN', tostring(v))\n"
        "  if v == nil then self:internalStorageSet('token', 'abc-123') end\n"
        "end\n"
    )

    # run 1: sets the internalStorage variable
    engine = LuaEngine(db_path=str(db), db_persist=True)
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "TOKEN nil" in out
    saved = json.loads(db.read_text(encoding="utf-8"))
    assert saved["qaState"]["store"]["variables"]["token"]["value"] == "abc-123"

    # run 2: the variable came back from the db
    engine = LuaEngine(db_path=str(db), db_persist=True)
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await wait_until(lambda: not engine.has_pending_work())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "TOKEN abc-123" in out
