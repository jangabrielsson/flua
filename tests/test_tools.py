"""The --tool registry: one module per tool, discovered automatically.

Adding a tool means adding a module to flua/tools/ exporting NAME, HELP,
add_arguments() and run() — no other file changes.
"""

import argparse
import base64
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("lupa")

from flua import tools  # noqa: E402


def test_registry_discovers_all_tools() -> None:
    assert tools.tool_names() == [
        "catalog",
        "createDB",
        "downloadFQA",
        "downloadQA",
        "house",
        "hub",
        "hubList",
        "icons",
        "installHelper",
        "migrate",
        "newQA",
        "pack",
        "parityCapture",
        "parityCleanup",
        "setup",
        "state",
        "typeinfo",
        "ui",
        "unpack",
        "updateQA",
        "uploadFQA",
        "uploadFile",
        "uploadQA",
        "ws",
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
    reject_export_post: bool = False  # firmware that 400s POST /quickApp/{id}/export

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
                    "type": "com.fibaro.zwavePrimaryController",
                    "properties": {"sunriseHour": "06:00", "sunsetHour": "21:30"},
                }
            )
        elif path == "/api/panels/location":
            self._send([{"id": 1, "name": "Home", "latitude": 57.7, "longitude": 11.97}])
        elif path.startswith("/api/devices/") and len(path.split("/")) == 4:
            device = type(self).devices.get(int(path.split("/")[3]))
            self._send(device if device is not None else {}, 200 if device else 404)
        elif path.startswith("/api/quickApp/export/"):
            qa_id = int(path.split("/")[-1])
            fqa = self.fqas.get(qa_id)
            if fqa is None:
                self._send({}, 404)
            else:
                self._send(fqa)
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
        elif path == "/api/quickApp/import":
            # the web UI's wire format: multipart/form-data with file + roomId
            ctype = self.headers.get("Content-Type", "")
            match = re.search(r"boundary=(.+)$", ctype)
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            if not match:
                self._send({}, 400)
                return
            boundary = match.group(1).strip().encode()
            fields: dict[str, str] = {}
            filenames: dict[str, str] = {}
            for part in raw.split(b"--" + boundary):
                part = part.strip(b"\r\n")
                if not part or part == b"--":
                    continue
                head, _, content = part.partition(b"\r\n\r\n")
                name = re.search(rb'name="([^"]+)"', head)
                if name:
                    fields[name.group(1).decode()] = content.decode("utf-8")
                    file_name = re.search(rb'filename="([^"]*)"', head)
                    if file_name:
                        filenames[name.group(1).decode()] = file_name.group(1).decode()
            try:
                fqa = json.loads(fields.get("file", ""))
            except Exception:
                self._send({}, 400)
                return
            self.fqas[self.next_id] = fqa
            type(self).requests.append(
                (
                    "POST",
                    path,
                    {
                        "file": fqa,
                        "roomId": fields.get("roomId"),
                        "filename": filenames.get("file"),
                    },
                )
            )
            self._send({"id": self.next_id, "name": fqa["name"]}, 201)
            self.next_id += 1
        elif path.startswith("/api/quickApp/export/"):
            # downloadQA's export-by-id endpoint
            qa_id = int(path.split("/")[-1])
            fqa = self.fqas.get(qa_id)
            if fqa is None:
                self._send({}, 404)
            else:
                self._send(fqa)
        elif path.startswith("/api/quickApp/") and path.endswith("/export"):
            # the real HC3 400s a BODYLESS export POST (live-verified) —
            # pin that contract; reject_export_post fakes the firmware that
            # rejects the POST altogether (the tool falls back to the GET)
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            if type(self).reject_export_post or not raw:
                self._send({}, 400)
                return
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


def _mock_hc3(tmp_path, monkeypatch) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("HC3_USER", "admin")
    monkeypatch.setenv("HC3_PASSWORD", "secret")
    monkeypatch.chdir(tmp_path)
    return server


def test_download_qa_writes_file_metadata(tmp_path, monkeypatch, capsys) -> None:
    # downloadQA stamps every unpacked file with --%%deviceId/--%%qaFile:
    # the main file in its generated header, extras as header lines — the
    # metadata --tool uploadFile reads for single-file updates
    _MockHc3.fqas = {
        100: {
            "name": "MyQA",
            "type": "com.fibaro.binarySwitch",
            "apiVersion": "1.3",
            "initialProperties": {"quickAppVariables": [], "useUiView": False},
            "initialInterfaces": [],
            "files": [
                {
                    "name": "main",
                    "isMain": True,
                    "isOpen": False,
                    "content": "function QuickApp:onInit() end\n",
                },
                {
                    "name": "lib",
                    "isMain": False,
                    "isOpen": False,
                    "content": "function helper() return 1 end\n",
                },
            ],
        }
    }
    server = _mock_hc3(tmp_path, monkeypatch)
    try:
        module = tools._TOOLS["downloadQA"]
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        assert module.run(parser, parser.parse_args(["100"])) == 0
        capsys.readouterr()
        # the default target directory is the QA's name
        project = tmp_path / "MyQA"
        main = (project / "MyQA_main_100.lua").read_text()
        assert "--%%deviceId:100" in main
        assert "--%%qaFile:main" in main
        lib = (project / "MyQA_lib_100.lua").read_text()
        assert lib.startswith("--%%deviceId:100\n--%%qaFile:lib\n")
        assert "function helper() return 1 end" in lib
    finally:
        server.shutdown()
        server.server_close()


def test_upload_file_pushes_single_file(tmp_path, monkeypatch, capsys) -> None:
    # the VS Code task flow: edit one downloaded file, push just that file —
    # the directives say which QA and which QA file name; isMain comes from
    # the name, and a name mismatch on the HC3 warns (stale copy) but uploads
    _MockHc3.requests = []
    _MockHc3.devices = {
        100: {"id": 100, "name": "MyQA", "type": "com.fibaro.binarySwitch", "properties": {}},
    }
    server = _mock_hc3(tmp_path, monkeypatch)
    try:
        edited = tmp_path / "MyQA_lib_100.lua"
        edited.write_text("--%%deviceId:100\n--%%qaFile:lib\nfunction helper() return 2 end\n")
        module = tools._TOOLS["uploadFile"]
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        assert module.run(parser, parser.parse_args(["MyQA_lib_100.lua"])) == 0
        out = capsys.readouterr().out
        assert "updated MyQA_lib_100.lua -> QA 100 file 'lib'" in out
        puts = [r for r in _MockHc3.requests if r[0] == "PUT" and r[1] == "/api/quickApp/100/files"]
        assert len(puts) == 1
        assert puts[0][2] == [
            {
                "name": "lib",
                "type": "lua",
                "isMain": False,
                "content": "--%%deviceId:100\n--%%qaFile:lib\nfunction helper() return 2 end\n",
            }
        ]
    finally:
        server.shutdown()
        server.server_close()


def test_upload_file_main_and_mismatch_warning(tmp_path, monkeypatch, capsys) -> None:
    # the main file: isMain=true and the message notes the restart; a device
    # name that no longer matches the file name warns about a stale copy
    _MockHc3.requests = []
    _MockHc3.devices = {
        100: {"id": 100, "name": "OtherName", "type": "com.fibaro.binarySwitch", "properties": {}},
    }
    server = _mock_hc3(tmp_path, monkeypatch)
    try:
        main = tmp_path / "MyQA_main_100.lua"
        main.write_text(
            "--%%name:MyQA\n--%%type:com.fibaro.binarySwitch\n"
            "--%%deviceId:100\n--%%qaFile:main\nfunction QuickApp:onInit() end\n"
        )
        module = tools._TOOLS["uploadFile"]
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        assert module.run(parser, parser.parse_args(["MyQA_main_100.lua"])) == 0
        out = capsys.readouterr().out
        assert "warning: file name says 'MyQA' but device 100 is named 'OtherName'" in out
        assert "the QA restarts" in out
        puts = [r for r in _MockHc3.requests if r[0] == "PUT"]
        assert puts and puts[0][2][0]["isMain"] is True
        assert puts[0][2][0]["name"] == "main"
    finally:
        server.shutdown()
        server.server_close()


def test_upload_file_falls_back_to_filename_convention(tmp_path, monkeypatch, capsys) -> None:
    # files downloaded before the directives existed still work: the
    # <Name>_<file>_<id>.lua filename carries the same metadata
    _MockHc3.requests = []
    _MockHc3.devices = {
        100: {"id": 100, "name": "MyQA", "type": "com.fibaro.binarySwitch", "properties": {}},
    }
    server = _mock_hc3(tmp_path, monkeypatch)
    try:
        legacy = tmp_path / "MyQA_util_100.lua"
        legacy.write_text("function util() return 1 end\n")
        module = tools._TOOLS["uploadFile"]
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        assert module.run(parser, parser.parse_args(["MyQA_util_100.lua"])) == 0
        out = capsys.readouterr().out
        assert "-> QA 100 file 'util'" in out
        puts = [r for r in _MockHc3.requests if r[0] == "PUT"]
        assert puts and puts[0][2][0]["name"] == "util"
    finally:
        server.shutdown()
        server.server_close()


def test_upload_file_without_target_errors(tmp_path, monkeypatch) -> None:
    server = _mock_hc3(tmp_path, monkeypatch)
    try:
        stray = tmp_path / "random.lua"
        stray.write_text("function x() end\n")
        module = tools._TOOLS["uploadFile"]
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        with pytest.raises(SystemExit) as exc:
            module.run(parser, parser.parse_args(["random.lua"]))
        assert exc.value.code == 2
    finally:
        server.shutdown()
        server.server_close()


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
    fqa = json.loads((tmp_path / "packed.fqa").read_text())  # <QA name>.fqa default
    assert fqa["name"] == "packed" and len(fqa["files"]) == 2
    # and back out as a project: <QA-name>_<file>.lua (the downloadQA pattern
    # without the id)
    unpack = tools._TOOLS["unpack"]
    parser = argparse.ArgumentParser()
    unpack.add_arguments(parser)
    assert unpack.run(parser, parser.parse_args(["packed.fqa", "-d", "proj"])) == 0
    assert "unpacked to proj/" in capsys.readouterr().out
    assert "--%%name:packed" in (tmp_path / "proj" / "packed_main.lua").read_text()


def test_pack_default_output_names(tmp_path, capsys, monkeypatch) -> None:
    # the default .fqa output is <QA name>.fqa — the --%%name — or MyQA.fqa
    # when the QA declares no name (never the file's own name like main.fqa)
    monkeypatch.chdir(tmp_path)
    pack = tools._TOOLS["pack"]
    parser = argparse.ArgumentParser()
    pack.add_arguments(parser)
    (tmp_path / "app.lua").write_text("--%%name:Lamp Hall\nprint('x')\n")
    assert pack.run(parser, parser.parse_args(["app.lua"])) == 0
    assert "packed Lamp Hall (1 files) to " in capsys.readouterr().out
    assert (tmp_path / "Lamp_Hall.fqa").exists()  # sanitized for the file system
    (tmp_path / "plain.lua").write_text("print('x')\n")
    assert pack.run(parser, parser.parse_args(["plain.lua"])) == 0
    assert (tmp_path / "MyQA.fqa").exists()  # no --%%name: the neutral default


def test_pack_carries_identity_properties(tmp_path, capsys, monkeypatch) -> None:
    # the identity properties a QA declares travel in the package —
    # --%%manufacturer/--%%model/--%%build/--%%uid/--%%properties:deviceRole —
    # while dynamic properties (value, log, ...) still stay out
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.lua").write_text(
        "--%%name:idprops\n"
        "--%%manufacturer:FooBar\n"
        "--%%model:Widget-2000\n"
        "--%%build:7\n"
        "--%%uid:9f8e7d6c-0000-4000-8000-000000000000\n"
        "--%%properties:deviceRole=Fan\n"
        "print('x')\n"
    )
    pack = tools._TOOLS["pack"]
    parser = argparse.ArgumentParser()
    pack.add_arguments(parser)
    assert pack.run(parser, parser.parse_args(["app.lua"])) == 0
    capsys.readouterr()
    fqa = json.loads((tmp_path / "idprops.fqa").read_text())
    props = fqa["initialProperties"]
    assert props["manufacturer"] == "FooBar"
    assert props["model"] == "Widget-2000"
    assert props["buildNumber"] == 7
    assert props["deviceRole"] == "Fan"  # the binarySwitch skeleton's "Light" stays out
    assert props["quickAppUuid"] == "9f8e7d6c-0000-4000-8000-000000000000"
    assert "value" not in props  # dynamic properties still do not travel


def test_pack_legacy_ui_matches_the_hc3_export_shape(tmp_path, capsys, monkeypatch) -> None:
    # regression: a legacy-UI package carrying uiView made the HC3's import
    # regenerate uiCallbacks with generated default names (ui<b2>OnReleased),
    # dropping the custom handlers (live-verified 5.22x). The HC3's own
    # export carries only viewLayout + uiCallbacks — pack must match it, so
    # a package someone else installs keeps its custom handler names.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.lua").write_text(
        "--%%name:uipack\n"
        "--%%type:com.fibaro.binarySwitch\n"
        '--%%u:{button="b2",text="Go",onReleased="zoneDownButton"}\n'
        '--%%u:{slider="dim",onChanged="setLevel"}\n'
        "function QuickApp:onInit() end\n"
    )
    pack = tools._TOOLS["pack"]
    parser = argparse.ArgumentParser()
    pack.add_arguments(parser)
    assert pack.run(parser, parser.parse_args(["app.lua"])) == 0
    capsys.readouterr()
    fqa = json.loads((tmp_path / "uipack.fqa").read_text())
    props = fqa["initialProperties"]
    assert "viewLayout" in props
    assert "uiView" not in props  # the uiView presence triggers the HC3's regeneration
    assert "useUiView" not in props
    # initialProperties.apiVersion marks the package as current-format: the
    # HC3's JSON create preserves the package verbatim only WITH it
    # (live-verified — the mangled-buttons saga's actual trigger)
    assert props["apiVersion"] == "1.3"
    callbacks = {(c["name"], c["eventType"]): c["callback"] for c in props["uiCallbacks"]}
    assert callbacks[("b2", "onReleased")] == "zoneDownButton"
    assert callbacks[("dim", "onChanged")] == "setLevel"
    # the package describes final, initialized properties (the HC3's own
    # exports carry true; false makes the import re-run type-template init
    # and re-derive uiCallbacks with generated defaults)
    assert props["typeTemplateInitialized"] is True
    assert "userDescription" not in props  # empties stay out like the HC3's exports
    # the uiView format travels when it is the active one
    (tmp_path / "ui2.lua").write_text(
        "--%%name:uipack2\n"
        "--%%type:com.fibaro.binarySwitch\n"
        "--%%useUiView:true\n"
        '--%%u:{button="b2",text="Go",onReleased="zoneDownButton"}\n'
        "function QuickApp:onInit() end\n"
    )
    assert pack.run(parser, parser.parse_args(["ui2.lua", "-o", "ui2.fqa"])) == 0
    capsys.readouterr()
    props = json.loads((tmp_path / "ui2.fqa").read_text())["initialProperties"]
    assert props["useUiView"] is True
    assert props["uiView"][0]["components"][0]["name"] == "b2"


def test_upload_and_download_fqa_tools(tmp_path, monkeypatch, capsys) -> None:
    _MockHc3.fqas = {}
    _MockHc3.next_id = 100
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        monkeypatch.chdir(tmp_path)
        (tmp_path / "qa.lua").write_text(
            "--%%name:roundtrip\n--%%type:com.fibaro.binarySwitch\nfunction QuickApp:onInit() end\n"
        )
        pack = tools._TOOLS["pack"]
        parser = argparse.ArgumentParser()
        pack.add_arguments(parser)
        assert pack.run(parser, parser.parse_args(["qa.lua", "-o", "qa.fqa"])) == 0
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


def test_upload_fqa_uses_the_web_import_endpoint(tmp_path, monkeypatch, capsys) -> None:
    # regression: POST /quickApp (the API-create path) makes the HC3
    # re-derive uiCallbacks with generated defaults, breaking custom button
    # handlers; the web UI's POST /quickApp/import (multipart) preserves the
    # package verbatim — uploadFQA/uploadQA must use it when the HC3 is real
    _MockHc3.fqas = {}
    _MockHc3.next_id = 100
    _MockHc3.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        monkeypatch.chdir(tmp_path)
        (tmp_path / "app.lua").write_text(
            "--%%name:uiflow\n--%%type:com.fibaro.binarySwitch\n"
            '--%%u:{button="b2",text="Go",onReleased="zoneDownButton"}\n'
            "function QuickApp:onInit() end\n"
        )
        pack = tools._TOOLS["pack"]
        parser = argparse.ArgumentParser()
        pack.add_arguments(parser)
        assert pack.run(parser, parser.parse_args(["app.lua", "-o", "app.fqa"])) == 0
        capsys.readouterr()
        upload = tools._TOOLS["uploadFQA"]
        parser = argparse.ArgumentParser()
        upload.add_arguments(parser)
        assert upload.run(parser, parser.parse_args(["app.fqa", "--room", "7"])) == 0
        out = capsys.readouterr().out
        assert "uploaded uiflow — HC3 device id 100" in out
        # the multipart import path was used, carrying the fqa verbatim
        posts = [
            r for r in _MockHc3.requests if r[0] == "POST" and r[1] == "/api/quickApp/import"
        ]
        assert len(posts) == 1
        assert posts[0][2]["roomId"] == "7"
        # the file part carries a filename — a filename-less part crashes
        # the HC3's import handler with a bodyless 500 (live-verified)
        assert posts[0][2]["filename"] == "uiflow.fqa"
        fqa = posts[0][2]["file"]
        callbacks = {
            (c["name"], c["eventType"]): c["callback"]
            for c in fqa["initialProperties"]["uiCallbacks"]
        }
        assert callbacks[("b2", "onReleased")] == "zoneDownButton"
    finally:
        server.shutdown()
        server.server_close()


def test_pack_proxy_mode_qa_is_silent_and_keeps_the_directive(
    tmp_path, capsys, monkeypatch, caplog
) -> None:
    # packing is credential-free by design, so --%%mode:proxy can never
    # engage there — the pack must not emit the offline "proxy disabled"
    # warning (that warning is for actually RUNNING the QA offline). The
    # directive still travels in the packed main file (the author's run-mode
    # intent for flua users of the package).
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.lua").write_text(
        "--%%name:px\n--%%mode:proxy\nprint('x')\n"
    )
    pack = tools._TOOLS["pack"]
    parser = argparse.ArgumentParser()
    pack.add_arguments(parser)
    with caplog.at_level(logging.WARNING):
        assert pack.run(parser, parser.parse_args(["app.lua"])) == 0
    assert "proxy disabled" not in caplog.text
    assert "proxy disabled" not in capsys.readouterr().out
    fqa = json.loads((tmp_path / "px.fqa").read_text())
    main = next(f for f in fqa["files"] if f["isMain"])
    assert "--%%mode:proxy" in main["content"]


def test_icons_download_enumerates_live_custom_sets(tmp_path, monkeypatch) -> None:
    # a live /api/icons listing a custom User set (uploadExternalIconSet)
    # extends the download list with the pattern-derived file names — the
    # checked-in manifest does not know those sets
    class _IconsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/icons":
                payload = json.dumps(
                    {
                        "device": [
                            {"id": 999, "iconSetName": "User999", "fileExtension": "svg"}
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _IconsHandler)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        from flua.tools.icons import _with_live_custom_sets

        wanted = [("ButtonSwitchV2", "ButtonSwitchV2.svg")]
        extended = _with_live_custom_sets(wanted)
        assert wanted == extended[:1]  # the manifest list stays first
        assert ("User999", "User999.svg") in extended
        assert ("User999", "User999Unknown.svg") in extended
        assert ("User999", "User999255.svg") in extended
        # a known set is not re-added
        assert sum(1 for pair in extended if pair[0] == "ButtonSwitchV2") == 1
    finally:
        server.shutdown()
        server.server_close()


def test_download_restores_identity_properties(tmp_path, monkeypatch) -> None:
    # the HC3's export omits manufacturer/model/... — both download tools
    # merge them back from /devices/{id} (only the identity keys, only
    # non-empty values)
    _MockHc3.fqas = {
        100: {
            "name": "ident",
            "type": "com.fibaro.binarySwitch",
            "initialProperties": {"quickAppVariables": []},
            "files": [{"name": "main", "isMain": True, "content": "print('x')\n"}],
        }
    }
    _MockHc3.devices = {
        100: {
            "id": 100,
            "name": "ident",
            "type": "com.fibaro.binarySwitch",
            "properties": {
                "manufacturer": "FooBar",
                "model": "Widget",
                "buildNumber": 9,
                "deviceRole": "Fan",
                "quickAppUuid": "u-u-i-d",
                "log": "",
            },
        }
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        monkeypatch.chdir(tmp_path)
        # downloadFQA: the saved package carries the identity properties
        module = tools._TOOLS["downloadFQA"]
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        assert module.run(parser, parser.parse_args(["100"])) == 0
        fqa = json.loads((tmp_path / "ident.fqa").read_text())
        props = fqa["initialProperties"]
        assert props["manufacturer"] == "FooBar"
        assert props["model"] == "Widget"
        assert props["buildNumber"] == 9
        assert props["deviceRole"] == "Fan"
        assert props["quickAppUuid"] == "u-u-i-d"
        assert "log" not in props  # only the identity keys are merged
        # downloadQA: the unpacked main regenerates them as --%%property lines
        module = tools._TOOLS["downloadQA"]
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        assert module.run(parser, parser.parse_args(["100"])) == 0
        main = (tmp_path / "ident" / "ident_main_100.lua").read_text()
        assert "--%%property:manufacturer=FooBar" in main
        assert "--%%property:model=Widget" in main
        assert "--%%property:buildNumber=9" in main
        assert "--%%property:deviceRole=Fan" in main
    finally:
        server.shutdown()
        server.server_close()


def test_download_fqa_falls_back_to_get_export(tmp_path, monkeypatch) -> None:
    # some firmware 400s POST /quickApp/{id}/export altogether —
    # downloadFQA falls back to the deprecated GET /quickApp/export/{id}
    # (the same proven fallback downloadQA uses), so the download works
    _MockHc3.fqas = {
        100: {
            "name": "fb",
            "type": "com.fibaro.binarySwitch",
            "initialProperties": {"quickAppVariables": []},
            "files": [{"name": "main", "isMain": True, "content": "print('x')\n"}],
        }
    }
    _MockHc3.reject_export_post = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHc3)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        monkeypatch.chdir(tmp_path)
        module = tools._TOOLS["downloadFQA"]
        parser = argparse.ArgumentParser()
        module.add_arguments(parser)
        assert module.run(parser, parser.parse_args(["100"])) == 0
        fqa = json.loads((tmp_path / "fb.fqa").read_text())
        assert fqa["name"] == "fb"
    finally:
        _MockHc3.reject_export_post = False
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
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
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
            "--%%manufacturer:FooBar\n"
            "--%%build:5\n"
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
        # uiView/useUiView are absent from a legacy package (the HC3's
        # standard export shape — carrying uiView makes the HC3's import
        # regenerate uiCallbacks with generated defaults), so they are not
        # synced
        assert {
            "viewLayout", "uiCallbacks", "userDescription",
            "manufacturer", "buildNumber",  # the declared identity properties sync too
        } <= names
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
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
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
        assert doc["devices"][0]["type"] == "com.fibaro.zwavePrimaryController"
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


def test_install_helper_decides_by_version() -> None:
    # installHelper is idempotent: same/newer helper = keep + reconnect,
    # older = delete + re-upload, absent = install
    from flua.tools.install_helper import _bundled_identity, _decide, _filter_helpers

    uuid, version = _bundled_identity()
    assert uuid and version  # the bundled source declares its identity

    def helper(ver: str, name: str = "FluaHelper") -> dict:
        return {"id": 1, "name": name, "properties": {"quickAppUuid": uuid, "model": ver}}

    assert _decide([], version) == ("install", None)
    same = helper(version)
    assert _decide([same], version) == ("skip", same)
    assert _decide([helper("1.0.0")], version)[0] == "replace"
    assert _decide([helper("9.9.9")], version)[0] == "skip"  # never downgrade
    # discovery is by quickAppUuid only: a RENAMED helper is still found,
    # an unrelated device named FluaHelper is not
    renamed = {
        "id": 2, "name": "Garage door",
        "properties": {"quickAppUuid": uuid, "model": "1.0.0"},
    }
    impostor = {"id": 3, "name": "FluaHelper", "properties": {}}
    assert _filter_helpers([same, renamed, impostor], uuid) == [same, renamed]
    # equal versions: the latest creation date wins the keep slot
    older = {"id": 4, "properties": {"quickAppUuid": uuid, "model": version}, "created": 100}
    newer = {"id": 5, "properties": {"quickAppUuid": uuid, "model": version}, "created": 200}
    decision, best = _decide([older, newer], version)
    assert decision == "skip" and best["id"] == 5
    # a newer version beats an older one regardless of creation order
    decision, best = _decide(
        [{"id": 6, "properties": {"quickAppUuid": uuid, "model": "1.0.0"}, "created": 999}],
        version,
    )
    assert decision == "replace"


def test_setup_tool_scaffolds_a_qa_project(tmp_path, capsys) -> None:
    module = tools._TOOLS["setup"]
    parser = argparse.ArgumentParser()
    module.add_arguments(parser)
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    out = capsys.readouterr().out
    # the VS Code configs, the LuaLS type library, and the agent files land
    # (the viewer is NOT copied — flua --ui serves it from the package)
    for path in (
        ".vscode/launch.json",
        ".vscode/extensions.json",
        ".luals/QuickApp.lua",
        ".luals/fibaro.lua",
        ".luals/api.lua",
        ".luarc.json",
        "AGENTS.md",
        ".github/copilot-instructions.md",
        ".github/instructions/quickapp-dev.instructions.md",
        ".github/prompts/install-qa-skills.prompt.md",
        ".github/skills/quickapp-api/SKILL.md",
    ):
        assert (tmp_path / path).exists(), path
    assert "wrote .luals" in out
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
    # VS Code's markdown preview; the flua extension drives the explorer tools
    extensions = (tmp_path / ".vscode/extensions.json").read_text()
    assert "bierner.markdown-mermaid" in extensions
    assert "GsonSoft-development.flua" in extensions
    # the common QA snippets (qa-header/qa-http/qa-rs/…) ship too — scoped
    # to Lua, and managed: refreshed while unmodified, kept once edited
    snippets_path = tmp_path / ".vscode" / "flua.code-snippets"
    assert snippets_path.exists()
    snippets = json.loads(snippets_path.read_text())
    assert snippets["QuickApp header"]["prefix"] == "qa-header"
    assert snippets["RefreshStateSubscriber"]["scope"] == "lua"
    snippets_path.write_text('{"mine": {"prefix": "x", "body": ["x"]}}\n')
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    assert "kept .vscode/flua.code-snippets" in capsys.readouterr().out
    assert "mine" in snippets_path.read_text()
    # idempotent: a second run keeps the existing files
    (tmp_path / "AGENTS.md").write_text("custom\n")
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    assert "kept AGENTS.md" in capsys.readouterr().out
    assert (tmp_path / "AGENTS.md").read_text() == "custom\n"
    # --force overwrites
    assert module.run(parser, parser.parse_args(["--force", str(tmp_path)])) == 0
    assert "flua" in (tmp_path / "AGENTS.md").read_text()


def test_setup_refreshes_vendor_files(tmp_path, capsys) -> None:
    # the skills, instructions and LuaLS stubs are flua's content: a re-run
    # after an upgrade overwrites them, even when locally edited (the
    # "pip install --upgrade" contract — user edits belong elsewhere)
    module = tools._TOOLS["setup"]
    parser = argparse.ArgumentParser()
    module.add_arguments(parser)
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    skill = tmp_path / ".github" / "skills" / "quickapp-api" / "SKILL.md"
    luarc = tmp_path / ".luarc.json"
    skill.write_text("local edits\n")
    luarc.write_text("{}\n")
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    out = capsys.readouterr().out
    assert "updated .github/skills" in out
    assert "updated .luarc.json" in out
    assert "local edits" not in skill.read_text()  # restored to the shipped content


def test_setup_refreshes_unmodified_agentes(tmp_path, capsys) -> None:
    # AGENTS.md is managed: refreshed while it still matches the shipped
    # template byte for byte, kept once the user has edited it
    module = tools._TOOLS["setup"]
    parser = argparse.ArgumentParser()
    module.add_arguments(parser)
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    assert module.run(parser, parser.parse_args([str(tmp_path)])) == 0
    out = capsys.readouterr().out
    assert "updated AGENTS.md" in out  # unchanged -> refreshed
    assert "locally modified" not in out


def test_setup_falls_back_to_bare_flua_when_not_on_path(tmp_path, capsys, monkeypatch) -> None:
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


def test_packaged_luarc_matches_the_repo() -> None:
    # the setup template's LuaLS config must match the repo's (Lua 5.5 +
    # HC3 globals + the .luals type library) so pip users get the same
    # diagnostics and autocomplete as contributors
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / ".luarc.json"
    origin = repo / ".luarc.json"
    assert packaged.read_bytes() == origin.read_bytes(), "sync .luarc.json into setup_templates"


def test_repo_vscode_snippets_match_the_setup_template() -> None:
    # the repo's own .vscode/flua.code-snippets is the same file --tool
    # setup ships to QA projects — a sync guard keeps the two identical
    repo = Path(__file__).resolve().parent.parent
    repo_copy = repo / ".vscode" / "flua.code-snippets"
    template = repo / "src" / "flua" / "setup_templates" / "vscode" / "flua.code-snippets"
    assert repo_copy.read_bytes() == template.read_bytes(), "sync the snippets into .vscode/"


def test_packaged_luals_library_matches_the_repo() -> None:
    # the LuaLS type definitions ship in the wheel for --tool setup; a sync
    # guard keeps the packaged copies identical to the repo's .luals/
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "luals"
    for origin in (repo / ".luals").rglob("*.lua"):
        copy = packaged / origin.relative_to(repo / ".luals")
        assert copy.exists(), f"missing packaged luals file: {copy}"
        assert copy.read_bytes() == origin.read_bytes(), f"drifted: {copy}"


def test_wheel_ships_bundled_lua_libraries() -> None:
    # --%%file:$name.lua resolves against src/flua/lua/lib — pyproject's
    # package-data must ship that directory, or pip users lose the libs
    import tomllib

    repo = Path(__file__).resolve().parent.parent
    with open(repo / "pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)
    flua_data = pyproject["tool"]["setuptools"]["package-data"]["flua"]
    assert "lua/lib/*.lua" in flua_data
    lib_dir = repo / "src" / "flua" / "lua" / "lib"
    assert lib_dir.is_dir() and list(lib_dir.glob("*.lua"))


def test_wheel_ships_every_example_file() -> None:
    # examples/ ships in the wheel as the flua.examples package — the
    # package-data globs must cover every file under examples/, or pip
    # users silently lose examples (fixtures, subdirectory demos, …)
    import fnmatch
    import tomllib

    repo = Path(__file__).resolve().parent.parent
    with open(repo / "pyproject.toml", "rb") as handle:
        pyproject = tomllib.load(handle)
    globs = pyproject["tool"]["setuptools"]["package-data"]["flua.examples"]
    examples = repo / "examples"
    uncovered: list[str] = []
    for path in examples.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.name == "__init__.py":
            continue  # ships as the package itself, not package-data
        relative = path.relative_to(examples).as_posix()
        if not any(fnmatch.fnmatch(relative, pattern) for pattern in globs):
            uncovered.append(relative)
    assert not uncovered, f"examples not covered by package-data globs: {uncovered}"


def test_packaged_skills_match_the_repo() -> None:
    # the wheel ships the skills; a sync guard keeps the copies honest
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "github" / "skills"
    for origin in (repo / ".github" / "skills").rglob("*"):
        if origin.is_file():
            copy = packaged / origin.relative_to(repo / ".github" / "skills")
            assert copy.exists(), f"missing packaged skill: {copy}"
            assert copy.read_bytes() == origin.read_bytes(), f"drifted: {copy}"


def test_packaged_docs_match_the_repo() -> None:
    # the flua-mcp resource tier serves the packaged docs from pip installs;
    # keep the copies honest like the skills (sync: scripts/sync-skills.sh)
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "docs"
    # build artifacts with embedded timestamps: rebuilt PDFs can never be
    # byte-identical — existence is the contract, sync-skills.sh ships them
    timestamped = {"flua-tutorial.pdf"}
    for origin in (repo / "docs").rglob("*"):
        if origin.is_file():
            copy = packaged / origin.relative_to(repo / "docs")
            assert copy.exists(), f"missing packaged doc: {copy}"
            if origin.name in timestamped:
                continue
            assert copy.read_bytes() == origin.read_bytes(), f"drifted: {copy}"
    for name in ("USAGE.md", "ARCHITECTURE.md", "CONTRIBUTING.md"):
        assert (packaged / name).read_bytes() == (repo / name).read_bytes(), f"drifted: {name}"
    # root README.md is deliberately not copied: docs/README.md (the docs
    # index) owns that name in the packaged tree, so flua://docs/README.md
    # is unambiguous — and the loop above already pinned it to docs/README.md
    assert (packaged / "README.md").read_bytes() == (repo / "docs" / "README.md").read_bytes()


def test_packaged_instructions_match_the_repo() -> None:
    # quickapp-dev.instructions.md lives in the repo (.github/instructions,
    # auto-applied to all *.lua work) and ships in the wheel — keep the
    # copies identical like the skills
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "github" / "instructions"
    for origin in (repo / ".github" / "instructions").rglob("*"):
        if origin.is_file():
            copy = packaged / origin.relative_to(repo / ".github" / "instructions")
            assert copy.exists(), f"missing packaged instructions file: {copy}"
            assert copy.read_bytes() == origin.read_bytes(), f"drifted: {copy}"


def test_sync_skills_script_restores_drift(tmp_path) -> None:
    # scripts/sync-skills.sh is the manual way back in sync: run it after a
    # deliberate drift and the packaged copies match the repo again. The test
    # runs against temp copies (SKILLS_SRC/SKILLS_DEST) so the repo tree is
    # never rewritten mid-suite — other tests read it concurrently.
    repo = Path(__file__).resolve().parent.parent
    skills = tmp_path / "skills"
    shutil.copytree(repo / ".github" / "skills", skills)
    packaged = tmp_path / "packaged"
    shutil.copytree(repo / "src" / "flua" / "setup_templates" / "github" / "skills", packaged)
    victim = packaged / "quickapp-types" / "SKILL.md"
    victim.write_bytes(victim.read_bytes() + b"\n<!-- drift -->\n")
    # the docs half of the sync gets temp targets too — never the repo tree
    docs = tmp_path / "docs-src"
    shutil.copytree(repo / "docs", docs)
    packaged_docs = tmp_path / "docs-packaged"
    packaged_docs.mkdir()
    doc_victim = packaged_docs / "walkthroughs.md"
    doc_victim.write_bytes(b"drifted\n")
    env = {
        **os.environ,
        "SKILLS_SRC": str(skills),
        "SKILLS_DEST": str(packaged),
        "DOCS_SRC": str(docs),
        "DOCS_DEST": str(packaged_docs),
    }
    result = subprocess.run(
        [str(repo / "scripts" / "sync-skills.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "synced" in result.stdout
    # the drift is gone: the packaged copy matches the skill dir again
    assert victim.read_bytes() == (skills / "quickapp-types" / "SKILL.md").read_bytes()
    assert "<!-- drift -->" not in victim.read_text(encoding="utf-8")
    # ...and the docs copy matches the docs tree (plus the root READMEs)
    assert doc_victim.read_bytes() == (docs / "walkthroughs.md").read_bytes()
    assert (packaged_docs / "USAGE.md").read_bytes() == (repo / "USAGE.md").read_bytes()


def test_tool_catalog_lists_device_types() -> None:
    # the answer to "unknown device type": the full --%%type catalog, as
    # lines and as JSON
    repo = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "catalog"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "com.fibaro.binarySwitch" in result.stdout
    assert "com.fibaro.multilevelSwitch" in result.stdout
    result_json = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "catalog", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    types = json.loads(result_json.stdout)
    assert isinstance(types, list) and "com.fibaro.binarySwitch" in types


def test_packaged_viewer_serves_from_the_package() -> None:
    # the wheel ships the UI viewer for --tool setup; --ui serves that same
    # packaged copy (src/flua/setup_templates/viewer/index.html) — the
    # repo's single source of truth for the viewer page
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "viewer" / "index.html"
    assert packaged.is_file()


def test_sanitize_filename() -> None:
    from flua.engine import sanitize_filename

    assert sanitize_filename("My QA!") == "My_QA"
    assert sanitize_filename("compiler-qa.v2") == "compiler_qa_v2"
    assert sanitize_filename("  ") == "qa"  # nothing usable left -> "qa"


def test_pack_bakes_package_values_into_dist_fqa(tmp_path, monkeypatch) -> None:
    # A distribution package (--tool pack / flua export) gets each --%%var's
    # PACKAGE value where declared (--%%var:name=expr,"<placeholder>" and the
    # --%%clobber alias), the evaluated value otherwise; unset (nil) variables
    # are dropped, and the main file's --%%var header lines are scrubbed to
    # the baked literals (no expression or secret literal travels).
    from flua.tools import common

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".flua.lua").write_text("return { secretPwd = 'hunter2', apiKey = 'sk-real' }\n")
    (tmp_path / "main.lua").write_text(
        "--%%name:pkg\n"
        "--%%type:com.fibaro.binarySwitch\n"
        "--%%var:pwd=config.secretPwd,'<set to service password>'\n"
        "--%%var:key=config.apiKey\n"
        "--%%var:legacy=config.legacyKey\n"
        "--%%clobber:legacy=<set in Plua>\n"
        "--%%var:opt=config.nothere\n"
        "--%%var:policy={alerts=true,units='C'}\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit() end\n"
    )
    fqa, _ = common.build_fqa("main.lua", dist=True)
    qv = {v["name"]: v["value"] for v in fqa["initialProperties"]["quickAppVariables"]}
    assert qv["pwd"] == "<set to service password>"
    assert qv["key"] == "sk-real"  # no package value -> the evaluated value
    assert qv["legacy"] == "<set in Plua>"  # --%%clobber is the same thing
    assert json.loads(qv["policy"]) == {"alerts": True, "units": "C"}
    assert "opt" not in qv  # evaluated nil -> not packaged
    main = next(f for f in fqa["files"] if f["isMain"])["content"]
    assert "--%%var:pwd='<set to service password>'" in main
    assert "config.secretPwd" not in main
    assert "hunter2" not in main
    assert "--%%clobber" not in main
    assert "--%%var:opt" not in main


def test_build_fqa_svar_bakes_password_type(tmp_path, monkeypatch) -> None:
    # --%%svar keeps type='password' in the baked package: a distribution
    # package ships the masked placeholder, a personal upload the real value
    from flua.tools import common

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".flua.lua").write_text("return { secretPwd = 'hunter2' }\n")
    (tmp_path / "main.lua").write_text(
        "--%%name:pkg\n"
        "--%%svar:pwd=config.secretPwd,'<set password>'\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit() end\n"
    )
    fqa, _ = common.build_fqa("main.lua", dist=True)
    assert fqa["initialProperties"]["quickAppVariables"] == [
        {"name": "pwd", "value": "<set password>", "type": "password"}
    ]
    main = next(f for f in fqa["files"] if f["isMain"])["content"]
    assert "--%%svar:pwd='<set password>'" in main
    assert "config.secretPwd" not in main
    assert "hunter2" not in main
    # personal upload: the real value, still password-typed
    fqa_up, _ = common.build_fqa("main.lua", dist=False)
    assert fqa_up["initialProperties"]["quickAppVariables"] == [
        {"name": "pwd", "value": "hunter2", "type": "password"}
    ]


def test_build_fqa_upload_bakes_real_values(tmp_path, monkeypatch) -> None:
    # A personal upload (--tool uploadQA) bakes the REAL evaluated values —
    # the placeholder is a distribution concern, your own HC3 gets the
    # credentials the QA needs.
    from flua.tools import common

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".flua.lua").write_text("return { secretPwd = 'hunter2' }\n")
    (tmp_path / "main.lua").write_text(
        "--%%name:up\n"
        "--%%var:pwd=config.secretPwd,'<placeholder>'\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit() end\n"
    )
    fqa, _ = common.build_fqa("main.lua", dist=False)
    assert fqa["initialProperties"]["quickAppVariables"] == [{"name": "pwd", "value": "hunter2"}]
    main = next(f for f in fqa["files"] if f["isMain"])["content"]
    assert "--%%var:pwd='hunter2'" in main


def test_packaged_var_errors_are_loud(tmp_path, monkeypatch) -> None:
    from flua.tools import common

    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.lua").write_text(
        "--%%clobber:nope=<x>\n-- --------------- EOH ---------------\n"
        "function QuickApp:onInit() end\n"
    )
    with pytest.raises(ValueError, match="names a variable without"):
        common.build_fqa("main.lua", dist=True)
    (tmp_path / "main.lua").write_text(
        "--%%var:pwd=config.x,'<a>'\n--%%clobber:pwd=<b>\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit() end\n"
    )
    with pytest.raises(ValueError, match="use one"):
        common.build_fqa("main.lua", dist=True)
    (tmp_path / "main.lua").write_text(
        "--%%var:boom=config.foo.bar.baz\n-- --------------- EOH ---------------\n"
        "function QuickApp:onInit() end\n"
    )
    with pytest.raises(ValueError, match="--%%var:boom"):
        common.build_fqa("main.lua", dist=True)


def test_packaged_timeline_serves_from_the_package() -> None:
    # the timeline page ships with the viewer; --ui serves it at /timeline
    repo = Path(__file__).resolve().parent.parent
    packaged = repo / "src" / "flua" / "setup_templates" / "viewer" / "timeline.html"
    assert packaged.is_file()


def test_timeline_page_and_trace_feed_end_to_end(tmp_path) -> None:
    # --ui serves /timeline, which polls /flua/systemLog — the trace entries
    # (--%%trace:api) carry the category data the timeline colors by
    import socket
    import subprocess
    import time
    import urllib.request

    script = tmp_path / "qa.lua"
    script.write_text(
        "--%%trace:api\n"
        "print('RUN')\n"
        "setTimeout(function() api.get('/devices/'.._FLUA.qaId) end, 100)\n"
        "setTimeout(function() exit(0) end, 400)\n"
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    process = subprocess.Popen(
        [sys.executable, "-m", "flua", "--ui", str(port), "--run-for", "8", str(script)],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        page = None
        while time.monotonic() < deadline:
            try:
                page = urllib.request.urlopen(f"http://127.0.0.1:{port}/timeline", timeout=2)
                break
            except OSError:
                time.sleep(0.2)
        assert page is not None, "the --ui server never came up"
        body = page.read().decode("utf-8")
        assert page.status == 200 and "flua timeline" in body
        # the feed the timeline polls: trace entries with their category
        deadline = time.monotonic() + 10
        entries = []
        while time.monotonic() < deadline and not entries:
            feed = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/flua/systemLog?last=0", timeout=2
            ).read()
            entries = json.loads(feed).get("entries") or []
            if not any(e.get("data", {}).get("category") == "api" for e in entries):
                entries = []
                time.sleep(0.2)
        assert any(e.get("data", {}).get("category") == "api" for e in entries), entries
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def test_icons_download_from_dump(tmp_path, capsys) -> None:
    # `--tool icons download --dump` copies the manifest-listed files that a
    # local webroot dump carries into the shared cache; already-cached files
    # are skipped unless --force; placeholder bodies (an SVG served under a
    # .png name) are dropped, never cached
    dump = tmp_path / "www" / "assets" / "icon" / "fibaro"
    (dump / "ButtonSwitchV2").mkdir(parents=True)
    (dump / "ButtonSwitchV2" / "ButtonSwitchV20.svg").write_bytes(b"<svg>off</svg>")
    (dump / "ButtonSwitchV2" / "ButtonSwitchV20.png").write_bytes(b"<svg>placeholder</svg>")
    cache = tmp_path / "cache"
    www = tmp_path / "www"

    assert tools.run_tool("icons", ["download", "--dump", str(www), "--dir", str(cache)]) == 0
    assert (cache / "ButtonSwitchV2" / "ButtonSwitchV20.svg").read_bytes() == b"<svg>off</svg>"
    assert not (cache / "ButtonSwitchV2" / "ButtonSwitchV20.png").exists()
    out = capsys.readouterr().out
    assert "copied 1 icon file(s)" in out
    assert "1 placeholder(s) dropped" in out

    # second run skips the cached file; --force copies it again
    assert tools.run_tool("icons", ["download", "--dump", str(www), "--dir", str(cache)]) == 0
    assert "skipped 1 cached" in capsys.readouterr().out
    (dump / "ButtonSwitchV2" / "ButtonSwitchV20.svg").write_bytes(b"<svg>new</svg>")
    assert (
        tools.run_tool("icons", ["download", "--dump", str(www), "--dir", str(cache), "--force"])
        == 0
    )
    assert (cache / "ButtonSwitchV2" / "ButtonSwitchV20.svg").read_bytes() == b"<svg>new</svg>"


def test_icons_download_user_sets_use_the_usericons_tree(tmp_path, capsys) -> None:
    # User<id> sets live under /assets/userIcons/devices as <set><state>.png
    # — the base plus the provider family's states. The dump's fibaro tree
    # holds placeholder art for them and is never consulted; the download
    # copies the real files and drops stale cached names outside the set's
    # candidate list.
    fibaro = tmp_path / "www" / "assets" / "icon" / "fibaro" / "User1001"
    fibaro.mkdir(parents=True)
    (fibaro / "User1001.svg").write_bytes(b"<svg>placeholder</svg>")
    (fibaro / "User100110.svg").write_bytes(b"<svg>placeholder state</svg>")
    usericons = tmp_path / "www" / "assets" / "userIcons" / "devices" / "User1001"
    usericons.mkdir(parents=True)
    (usericons / "User1001.png").write_bytes(b"\x89PNGbase")
    (usericons / "User1001100.png").write_bytes(b"\x89PNGstate")
    cache = tmp_path / "cache"
    # a stale placeholder state file from an earlier download must be cleaned
    (cache / "User1001").mkdir(parents=True)
    (cache / "User1001" / "User1001.svg").write_bytes(b"<svg>stale</svg>")

    assert (
        tools.run_tool(
            "icons", ["download", "--dump", str(tmp_path / "www"), "--dir", str(cache)]
        )
        == 0
    )
    assert (cache / "User1001" / "User1001.png").read_bytes() == b"\x89PNGbase"
    assert (cache / "User1001" / "User1001100.png").read_bytes() == b"\x89PNGstate"
    assert not (cache / "User1001" / "User1001.svg").exists()
    out = capsys.readouterr().out
    assert "copied 2 icon file(s)" in out


def test_icons_hc3_download_user_sets_use_usericons(tmp_path, monkeypatch) -> None:
    # the live path fetches a user set's files from the userIcons tree —
    # the base plus the provider family's states — and never touches the
    # fibaro tree (placeholder art for these sets)
    requests: list[str] = []
    real = {
        "User999.png": b"\x89PNGbase",
        "User9990.png": b"\x89PNGoff",
        "User999100.png": b"\x89PNGon",
    }

    class _IconsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            prefix = "/assets/userIcons/devices/User999/"
            if self.path.startswith(prefix) and self.path[len(prefix) :] in real:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(real[self.path[len(prefix) :]])
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _IconsHandler)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        from flua.tools.icons import _from_hc3

        cache = tmp_path / "cache"
        (cache / "User999").mkdir(parents=True)
        (cache / "User999" / "User99910.svg").write_bytes(b"<svg>stale</svg>")
        assert (
            _from_hc3(
                [("User999", "User999.png"), ("User999", "User99910.png")],
                cache,
                force=False,
            )
            == 0
        )
        assert "/assets/userIcons/devices/User999/User999.png" in requests
        assert "/assets/userIcons/devices/User999/User9990.png" in requests
        assert "/assets/userIcons/devices/User999/User999100.png" in requests
        # the fibaro tree is never consulted for user sets
        assert all(r.startswith("/assets/userIcons/devices/User999/") for r in requests)
        assert (cache / "User999" / "User999.png").read_bytes() == b"\x89PNGbase"
        assert (cache / "User999" / "User9990.png").read_bytes() == b"\x89PNGoff"
        assert (cache / "User999" / "User999100.png").read_bytes() == b"\x89PNGon"
        assert not (cache / "User999" / "User99910.svg").exists()
    finally:
        server.shutdown()
        server.server_close()


def test_icon_placeholder_detects_html_error_docs(tmp_path) -> None:
    # the userIcons tree serves HTML error docs for missing files — those
    # are placeholders too, not artwork
    from flua.tools.icons import _is_placeholder

    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG")
    assert not _is_placeholder(png)
    svg = tmp_path / "z.svg"
    svg.write_bytes(b"<svg></svg>")
    assert not _is_placeholder(svg)
    for name in ("y.png", "w.svg"):
        doc = tmp_path / name
        doc.write_bytes(b"<!doctype html><html></html>")
        assert _is_placeholder(doc), name


def test_migrate_tool_scans_a_project(tmp_path, capsys) -> None:
    # one-pass plua-migration scan: directive spellings, plua-only
    # directives, script invocations, stale packages, baked IPs
    (tmp_path / "qa.lua").write_text(
        "-- %%save:Old.fqa\n"
        "--%%headers:defaults.lua\n"
        '--%%var:IP="192.168.50.165"\n'
        "--%%name=OldStyle\n"
        "print('hi')\n"
    )
    (tmp_path / "dist").mkdir()
    old_fqa = tmp_path / "dist" / "Old.fqa"
    old_fqa.write_text('{"files": [{"name": "main", "type": "lua"}]}')
    import os

    os.utime(old_fqa, (0, 0))  # predates the sources: stale
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "build.sh").write_text("plua -t pack main.lua out.fqa\n")
    assert tools.run_tool("migrate", [str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "space before %%" in out
    assert "--%%include" in out  # the headers replacement
    assert "bakes a literal IP" in out
    assert "legacy directive spelling" in out
    assert "plua binary invocation" in out
    assert "pre-flua-format package" in out
    assert "stale package" in out
    assert "7 finding(s)" in out


def test_migrate_tool_clean_project_exits_zero(tmp_path, capsys) -> None:
    (tmp_path / "qa.lua").write_text("--%%name:Clean\nprint('hi')\n")
    assert tools.run_tool("migrate", ["--json", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_migrate_tool_flags_legacy_file_colon_form(tmp_path, capsys) -> None:
    # --%%file:path:name is the pre-plua spelling — flua reads path,name, so
    # the whole value becomes the path; say so with a migration hint
    (tmp_path / "qa.lua").write_text("--%%file:lib.lua:Lib\n")
    assert tools.run_tool("migrate", [str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "legacy --%%file:path:name spelling" in out
    assert "--%%file:path,name" in out


def test_upload_body_carries_raw_utf8_names() -> None:
    # the HC3 stores whatever bytes arrive: ASCII-escaped names get
    # re-encoded as Latin-1 (mojibake in the UTF-8 UI), raw UTF-8 passes
    # through intact (plua-verified). The {file: base64} envelope must
    # carry the raw UTF-8 bytes.
    import base64
    import json

    from flua.tools.upload_qa import _upload_body

    fqa = {"name": "Test åäöÅÄÖ", "type": "com.fibaro.binarySwitch", "files": []}
    body = _upload_body(fqa, 7)
    wire = base64.b64decode(body["file"])
    assert "åäöÅÄÖ".encode() in wire  # raw UTF-8 on the wire
    assert json.loads(wire)["name"] == "Test åäöÅÄÖ"  # and the name survives
    assert body["roomId"] == 7


def test_typeinfo_reports_the_qa_contract(tmp_path) -> None:
    # a type: flattened properties/actions with provenance, and the
    # QuickApp-methods framing; an interface: what it contributes
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "typeinfo", "com.fibaro.binarySwitch"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "com.fibaro.binarySwitch" in result.stdout
    assert "autoOffTimestamp" in result.stdout  # from the autoTurnOff interface
    assert "dead" in result.stdout  # from the base chain
    assert "QuickApp:<name>" in result.stdout
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "typeinfo", "autoTurnOff", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["kind"] == "interface"
    assert payload["properties"]["autoOffDefaultTime"]["default"] == 900
    assert payload["actions"]["setAutoOff"]["from"] == "interface"
    result = subprocess.run(
        [sys.executable, "-m", "flua", "--tool", "typeinfo", "com.fibaro.bogusType"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2


def _test_png(w: int = 128, h: int = 128, rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_icons_ui_manager_proxies_the_hc3(tmp_path, monkeypatch) -> None:
    # the manager's server talks to the HC3 (auth server-side, never in the
    # page) while the browser only talks to localhost: list + preview relay,
    # upload builds the live-verified HC3 multipart, delete sends the
    # four-param DELETE
    seen: list[tuple] = []

    class _Hc3(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(("GET", self.path, self.headers.get("Authorization")))
            if self.path == "/api/icons":
                payload = json.dumps(
                    {
                        "device": [
                            {
                                "id": 1001,
                                "deviceType": "com.fibaro.genericDevice",
                                "iconSetName": "User1001",
                                "fileExtension": "png",
                            },
                            {
                                "id": 998,
                                "deviceType": "com.fibaro.binarySwitch",
                                "iconSetName": "User998",
                                "fileExtension": "png",
                            },
                        ],
                        "room": [
                            {"id": 44, "iconName": "User44", "fileExtension": "png"}
                        ],
                        "scene": [
                            {"id": 55, "iconName": "User55", "fileExtension": "png"}
                        ],
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path.startswith("/assets/userIcons/devices/User1001/"):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(b"\x89PNGpreview")
                return
            if self.path.startswith("/assets/userIcons/rooms/User44/"):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(b"\x89PNGroom")
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            seen.append(
                ("POST", self.path, self.headers.get("Content-Type"), self.rfile.read(length))
            )
            if self.path == "/api/icons":
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":1234,"iconSetName":"User1234","fileExtension":"png"}')
                return
            self.send_response(404)
            self.end_headers()

        def do_DELETE(self):
            seen.append(("DELETE", self.path, self.headers.get("Authorization")))
            if self.path.startswith("/api/icons?"):
                self.send_response(200)
                self.end_headers()
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    hc3 = ThreadingHTTPServer(("127.0.0.1", 0), _Hc3)
    threading.Thread(target=hc3.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        monkeypatch.setenv("HC3_URL", f"http://127.0.0.1:{hc3.server_port}")
        monkeypatch.setenv("HC3_USER", "admin")
        monkeypatch.setenv("HC3_PASSWORD", "secret")
        from flua.tools.icons import serve_icons_ui

        server = serve_icons_ui(0)
        threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            page = urllib.request.urlopen(f"{base}/", timeout=10).read()
            assert b"HC3 Icon Manager" in page

            data = json.loads(urllib.request.urlopen(f"{base}/api/list", timeout=10).read())
            assert [e["iconSetName"] for e in data["icons"]["device"]] == [
                "User1001",
                "User998",
            ]
            assert [e["iconName"] for e in data["icons"]["room"]] == ["User44"]
            assert [e["iconName"] for e in data["icons"]["scene"]] == ["User55"]

            body = urllib.request.urlopen(
                f"{base}/api/preview?cat=room&set=User44&file=User44.png", timeout=10
            ).read()
            assert body == b"\x89PNGroom"

            body = urllib.request.urlopen(
                f"{base}/api/preview?set=User1001&file=User1001.png", timeout=10
            ).read()
            assert body == b"\x89PNGpreview"

            png = _test_png()
            request = urllib.request.Request(
                f"{base}/api/upload",
                data=json.dumps(
                    {
                        "deviceTemplate": "com.fibaro.binarySwitch",
                        "files": {
                            "icon0": base64.b64encode(png).decode(),
                            "icon100": base64.b64encode(png).decode(),
                        },
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            response = urllib.request.urlopen(request, timeout=10)
            assert response.status == 201
            post = next(x for x in seen if x[0] == "POST")
            multipart = post[3]
            assert b'name="type"' in multipart and b"\r\n\r\ndevice\r\n" in multipart
            assert b'name="deviceTemplate"' in multipart and b"com.fibaro.binarySwitch" in multipart
            assert b'name="icon0"' in multipart and b'name="icon100"' in multipart
            assert multipart.count(b"\x89PNG") == 2

            # a too-small icon is refused before the HC3 sees it
            small = _test_png(32, 32)
            request = urllib.request.Request(
                f"{base}/api/upload",
                data=json.dumps(
                    {
                        "deviceTemplate": "com.fibaro.binarySwitch",
                        "files": {"icon0": base64.b64encode(small).decode()},
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(request, timeout=10)
                raise AssertionError("small icon should be refused")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
                assert "128" in exc.read().decode()

            request = urllib.request.Request(
                f"{base}/api/delete",
                data=json.dumps(
                    {"id": 998, "name": "User998", "fileExtension": "png"}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            assert urllib.request.urlopen(request, timeout=10).status == 200
            deletes = [x for x in seen if x[0] == "DELETE"]
            assert any(
                "type=device" in path and "id=998" in path and "name=User998" in path
                for _, path, _ in deletes
            )

            # a room upload uses the single-icon contract (type=room + icon)
            request = urllib.request.Request(
                f"{base}/api/upload",
                data=json.dumps(
                    {
                        "category": "room",
                        "files": {"icon": base64.b64encode(png).decode()},
                        "fileExtension": "png",
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            assert urllib.request.urlopen(request, timeout=10).status == 201
            room_post = [x for x in seen if x[0] == "POST"][-1]
            room_body = room_post[3]
            assert b'name="type"' in room_body and b"\r\n\r\nroom\r\n" in room_body
            assert b'name="icon"' in room_body and b"\x89PNG" in room_body
            assert b'name="fileExtension"' in room_body and b"png" in room_body

            # a scene delete sends type=scene
            request = urllib.request.Request(
                f"{base}/api/delete",
                data=json.dumps(
                    {"category": "scene", "id": 55, "name": "User55", "fileExtension": "png"}
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            assert urllib.request.urlopen(request, timeout=10).status == 200
            assert any(
                "type=scene" in path and "id=55" in path
                for _, path, _ in [x for x in seen if x[0] == "DELETE"]
            )
        finally:
            server.shutdown()
            server.server_close()
    finally:
        hc3.shutdown()
        hc3.server_close()
