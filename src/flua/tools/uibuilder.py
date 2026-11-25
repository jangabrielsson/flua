"""uibuilder: a web page that builds QuickApp UIs visually and emits the
``--%%u`` / ``--%%rsrc`` directives (ADR 0016).

Stateless: the browser holds the row model, the server only compiles and
parses. The preview iframes the regular UI viewer against a synthetic
device, so what you see is the viewer's real renderer.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..config import parse_annotations
from ..ui import child_bindings, compile_ui, lua_literal

NAME = "uibuilder"
HELP = (
    "open the visual UI builder in a browser — build a QuickApp UI (main QA "
    "v1/v2 or a child device) and copy out the --%%u/--%%rsrc directives"
)

_PAGE = Path(__file__).parent.parent / "setup_templates" / "uibuilder" / "index.html"
_VIEWER = Path(__file__).parent.parent / "setup_templates" / "viewer" / "index.html"

# the server's only state: the last compiled preview
_state: dict[str, Any] = {"ui_view": [], "target": "main-v2"}


def compile_target(target: str, rows: Any, resource_name: str = "") -> dict[str, Any]:
    """rows (the --%%u shape) -> compiled structures + the directive text for
    the target. Target: main-v1 | main-v2 | child."""
    if not isinstance(rows, list):
        raise ValueError("rows must be a list of rows")
    ui = compile_ui(rows, 5000)
    if target == "child":
        ui_view = child_bindings(ui["uiView"], ui["uiCallbacks"])
        name = resource_name.strip() or "ui"
        # one directive per ROW (the --%%u shape): repeated directives with
        # the same name accumulate the resource's rows
        directives = [f"--%%rsrc:{name}:{lua_literal(row)}" for row in rows]
        return {"uiView": ui_view, "directives": directives}
    if target == "main-v1":
        return {
            "uiView": ui["uiView"],
            "viewLayout": ui["viewLayout"],
            "uiCallbacks": ui["uiCallbacks"],
            "directives": [f"--%%u:{lua_literal(row)}" for row in rows],
        }
    # main-v2
    return {
        "uiView": ui["uiView"],
        "uiCallbacks": ui["uiCallbacks"],
        "directives": [f"--%%u:{lua_literal(row)}" for row in rows],
    }


def parse_directives(text: str) -> dict[str, Any]:
    """Pasted --%%u/--%%rsrc directives -> the builder's row model. The
    --%%rsrc entries merge by name (repeated directives accumulate rows)."""
    annotations = parse_annotations(text, warn_unknown=False)
    resources: dict[str, list[Any]] = {}
    for entry in annotations.get("rsrc") or []:
        resources.setdefault(str(entry["name"]), []).extend(entry["rows"])
    return {
        "rows": annotations.get("u") or [],
        "resources": [{"name": name, "rows": rows} for name, rows in resources.items()],
    }


def _preview_device() -> dict[str, Any]:
    return {
        "id": 999001,
        "name": "preview",
        "type": "com.fibaro.genericDevice",
        "properties": {"uiView": _state.get("ui_view") or [], "useUiView": True, "log": ""},
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:  # quiet
        pass

    def _json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._html(200, _PAGE.read_bytes() if _PAGE.is_file() else b"uibuilder page missing")
        elif path == "/viewer":
            self._html(200, _VIEWER.read_bytes() if _VIEWER.is_file() else b"viewer missing")
        elif path == "/flua/devices":
            self._json(200, [_preview_device()])
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            body = {}
        path = self.path.split("?", 1)[0]
        if path == "/flua/uibuilder/compile":
            try:
                result = compile_target(
                    str(body.get("target") or "main-v2"),
                    body.get("rows"),
                    str(body.get("resourceName") or ""),
                )
                _state["ui_view"] = result["uiView"]
                _state["target"] = body.get("target")
                self._json(200, result)
            except Exception as exc:  # the page shows the message
                self._json(400, {"error": str(exc)})
        elif path == "/flua/uibuilder/parse":
            try:
                self._json(200, parse_directives(str(body.get("text") or "")))
            except Exception as exc:
                self._json(400, {"error": str(exc)})
        else:
            self._json(404, {"error": "not found"})


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("port", nargs="?", type=int, help="port (default: a free one)")


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port or 0), _Handler)
    except OSError as exc:
        parser.error(f"cannot start uibuilder: {exc}")
    print(f"flua uibuilder on http://127.0.0.1:{server.server_address[1]}/ — Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
