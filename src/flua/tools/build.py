"""build: the QA builder — a browser page that turns recipes into QAs.

The non-programmer funnel: pick a recipe, pick the real devices/rooms/
scenes from dropdowns fed by the live HC3, tweak values, and flua bakes
the values into the recipe's marked --%%var lines. The recipe index comes
from the flua repo (raw.githubusercontent, the iconInstall channel) with a
local cache and the shipped snapshot as the offline fallback — a new
recipe is one merge, no release.
"""

from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from ..http import http_call

NAME = "build"
HELP = "QA builder: a browser page to turn recipes into QuickApps"

RECIPES_ROOT = Path(__file__).resolve().parent.parent / "setup_templates" / "recipes"
INDEX_URL = "https://raw.githubusercontent.com/jangabrielsson/flua/main/recipes/index.json"
RECIPE_URL = "https://raw.githubusercontent.com/jangabrielsson/flua/main/recipes/{id}/main.lua"
_CACHE_ROOT = Path.home() / ".flua" / "recipes"
_SIM_SPEED = 600.0  # 1 wall second = 10 virtual minutes in the sim

_PAGE_PATH = Path(__file__).resolve().parent.parent / "setup_templates" / "qa_builder.html"


def _lua_literal(value: object) -> str:
    """A picked param value as a Lua literal for the --%%var line."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def bake_params(code: str, params: dict[str, object]) -> str:
    """Replace the recipe's marked --%%var lines with the picked values —
    plain, readable string surgery (the result is ordinary Lua). The whole
    value up to a trailing comment is replaced; the comment stays."""
    for name, value in params.items():
        line_re = re.compile(rf"^(--%%var:{re.escape(str(name))}=).*?(\s*--.*)?$", re.M)
        literal = _lua_literal(value)
        code = line_re.sub(
            lambda match, lit=literal: f"{match.group(1)}{lit}{match.group(2) or ''}", code
        )
    return code


def _fetch(url: str, timeout: float = 15.0) -> tuple[int, str]:
    status, body, _headers = http_call("GET", url, timeout=timeout)
    return status, body if isinstance(body, str) else body.decode(errors="replace")


def refresh_recipes() -> dict[str, object]:
    """Fetch the live index + every recipe's main.lua from the flua repo,
    cache under ~/.flua/recipes, return the index. Falls back to the
    shipped snapshot when GitHub cannot answer."""
    status, body = _fetch(INDEX_URL)
    if status == 200:
        try:
            index = json.loads(body)
        except ValueError:
            index = None
        if isinstance(index, dict) and isinstance(index.get("recipes"), list):
            _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
            (_CACHE_ROOT / "index.json").write_text(body, encoding="utf-8")
            for recipe in index["recipes"]:
                rid = recipe.get("id")
                if not isinstance(rid, str):
                    continue
                status, code = _fetch(RECIPE_URL.format(id=rid))
                if status == 200:
                    (_CACHE_ROOT / f"{rid}.lua").write_text(code, encoding="utf-8")
            return index
    return shipped_index()


def cached_index() -> dict[str, object]:
    """The last refreshed index, when one exists; otherwise the shipped
    snapshot (the no-network default)."""
    cached = _CACHE_ROOT / "index.json"
    try:
        index = json.loads(cached.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = None
    if isinstance(index, dict):
        return index
    return shipped_index()


def shipped_index() -> dict[str, object]:
    """The wheel's snapshot — the offline fallback."""
    path = RECIPES_ROOT / "index.json"
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"recipes": []}
    return index if isinstance(index, dict) else {"recipes": []}


def _recipe_code(rid: str) -> str | None:
    cached = _CACHE_ROOT / f"{rid}.lua"
    if cached.is_file():
        return cached.read_text(encoding="utf-8")
    shipped = RECIPES_ROOT / rid / "main.lua"
    if shipped.is_file():
        return shipped.read_text(encoding="utf-8")
    status, code = _fetch(RECIPE_URL.format(id=rid))
    return code if status == 200 else None


def _manifest_for(rid: str) -> dict[str, object] | None:
    for recipe in cached_index().get("recipes", []):
        if recipe.get("id") == rid:
            return recipe
    return None


async def _run_simulation(
    code: str, manifest: dict[str, object] | None, minutes: int, log_path: Path
) -> dict[str, object]:
    """Boot the generated QA in the offline sim and run it for ``minutes``
    virtual minutes (the clock runs 600x, so 1 wall second = 10 virtual
    minutes). Picked device ids are re-pointed at bundled sim devices of
    the matching kind, so the QA polls a real sim world instead of empty
    air. Returns {error, devices, virtualMinutes}; the log lands in
    log_path."""
    from ..engine import SIM_DEVICES_DIR, LuaEngine

    minutes = max(1, min(int(minutes or 5), 30))
    engine = LuaEngine(speed=_SIM_SPEED, api_mode="local")
    engine.set_log_mode("text", str(log_path))
    seeded: list[dict[str, object]] = []
    params: dict[str, object] = {}
    qa_info: dict[str, object] | None = None
    error: str | None = None
    await engine.start()
    try:
        if manifest:
            for param in manifest.get("params", []):
                if param.get("kind") != "device" or not param.get("filter"):
                    continue
                name = str(param["name"])
                baked = re.search(rf"^--%%var:{re.escape(name)}=(\d+)", code, re.M)
                if not baked or int(baked.group(1)) == 0:
                    continue  # unset — the recipe prints its hint instead
                kind = str(param["filter"]).split(".")[-1]
                if not (SIM_DEVICES_DIR / f"{kind}.lua").is_file():
                    continue
                sim_id, sim_err = engine.load_sim_device(kind)
                if sim_id is None:
                    error = f"sim device {kind}: {sim_err}"
                    break
                params[name] = sim_id
                seeded.append({"name": name, "kind": kind, "simId": sim_id})
        if error is None:
            run_code = bake_params(code, params) if params else code
            qa_path = engine.qa_temp_file(run_code)
            qa_id, qa_err = engine.load_qa_file(qa_path)
            if qa_id is None:
                error = qa_err or "cannot load the QA"
            else:
                qa_info = {
                    "id": qa_id,
                    "name": (manifest or {}).get("title") or "QuickApp",
                }
        if error is None:
            await asyncio.sleep(minutes * 60 / _SIM_SPEED + 0.05)
    finally:
        await engine.stop()
    clock = datetime.fromtimestamp(engine.clock.time).strftime("%d.%m.%Y %H:%M:%S")
    return {
        "error": error,
        "devices": seeded,
        "virtualMinutes": minutes,
        "qa": qa_info,
        "clock": clock,
    }


class _BuilderHandler(http.server.BaseHTTPRequestHandler):
    server: BuilderServer

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/":
            page = _PAGE_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        if parsed.path == "/api/index":
            query = urllib.parse.parse_qs(parsed.query)
            index = refresh_recipes() if query.get("refresh") else cached_index()
            self._json(200, index)
            return
        if parsed.path.startswith("/api/recipe/"):
            rid = urllib.parse.unquote(parsed.path[len("/api/recipe/") :])
            if not re.fullmatch(r"[a-z0-9-]+", rid):
                self._json(400, {"error": "bad recipe id"})
                return
            code = _recipe_code(rid)
            if code is None:
                self._json(404, {"error": "recipe not found"})
                return
            self._json(200, {"id": rid, "code": code})
            return
        if parsed.path in ("/api/devices", "/api/rooms", "/api/scenes"):
            self._proxy_hc3()
            return
        self._json(404, {"error": "not found"})

    def _proxy_hc3(self) -> None:
        if not self.server.hc3_base:
            self._json(200, {"hc3": None, "items": []})
            return
        try:
            # self.path keeps the query — isTypeOf filters pass through to
            # the HC3 (the sim implements them too)
            status, body, _headers = http_call(
                "GET",
                f"{self.server.hc3_base}{self.path}",
                {"Authorization": self.server.hc3_auth},
            )
        except OSError as exc:
            self._json(502, {"error": f"cannot reach the HC3: {exc}"})
            return
        if status != 200 or not isinstance(body, str):
            self._json(502, {"error": f"HC3 answered {status}"})
            return
        data = json.loads(body)
        items = [
            {"id": e.get("id"), "name": e.get("name"), "type": e.get("type")}
            for e in data
            if isinstance(e, dict)
        ]
        self._json(200, {"hc3": self.server.hc3_base, "items": items})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "bad JSON"})
            return
        if parsed.path == "/api/generate":
            rid = str(request.get("id") or "")
            code = _recipe_code(rid)
            if code is None:
                self._json(404, {"error": "recipe not found"})
                return
            params = request.get("params")
            if not isinstance(params, dict):
                self._json(400, {"error": "params must be an object"})
                return
            generated = bake_params(code, params)
            self._json(200, {"id": rid, "code": generated})
            return
        if parsed.path == "/api/download":
            rid = str(request.get("id") or "")
            code = _recipe_code(rid)
            if code is None:
                self._json(404, {"error": "recipe not found"})
                return
            params = request.get("params")
            generated = bake_params(code, params if isinstance(params, dict) else {})
            body = generated.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/x-lua")
            self.send_header("Content-Disposition", f'attachment; filename="{rid}.lua"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/upload":
            code = request.get("code")
            if not isinstance(code, str) or not code.strip():
                self._json(400, {"error": "code is required"})
                return
            device, error = _upload_generated(code)
            if error is not None:
                self._json(502, {"error": error})
                return
            self._json(200, {"device": device})
            return
        if parsed.path == "/api/simulate":
            rid = str(request.get("id") or "")
            code = request.get("code")
            if not isinstance(code, str) or not code.strip():
                self._json(400, {"error": "code is required"})
                return
            try:
                minutes = int(request.get("minutes"))
            except (TypeError, ValueError):
                minutes = 5
            manifest = _manifest_for(rid) if re.fullmatch(r"[a-z0-9-]+", rid) else None
            log_path = _CACHE_ROOT.parent / "sim.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            result = asyncio.run(_run_simulation(code, manifest, minutes, log_path))
            try:
                result["log"] = log_path.read_text(encoding="utf-8")
            except OSError:
                result["log"] = ""
            self._json(200, result)
            return
        self._json(404, {"error": "not found"})

    def log_message(self, *args: object) -> None:
        pass  # quiet — the tool's own output is enough


class BuilderServer(http.server.ThreadingHTTPServer):
    def __init__(self, port: int, hc3_base: str | None, hc3_auth: str | None):
        self.hc3_base = hc3_base
        self.hc3_auth = hc3_auth
        super().__init__(("127.0.0.1", port), _BuilderHandler)


def _hc3() -> tuple[str | None, str | None, str | None, str | None]:
    """(base_url, user, password, auth_header) from the .env chain — all
    None offline (the pickers fall back to typed ids)."""
    from ..environment import EnvChain

    chain = EnvChain(Path(__file__).resolve().parent.parent.parent)
    url = chain.get("HC3_URL")
    if not url:
        return None, None, None, None
    base = url.rstrip("/")
    if base.endswith("/api"):
        base = base[: -len("/api")]
    import base64

    user = chain.get("HC3_USER")
    password = chain.get("HC3_PASSWORD")
    auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    return base, user, password, auth


def _upload_generated(code: str) -> tuple[dict[str, object] | None, str | None]:
    """Build + upload the generated QA through the import endpoint (the
    package-preserving path). Returns (device, error)."""
    from ..engine import sanitize_filename
    from ..hc3 import Hc3Remote
    from .common import build_fqa

    base, user, password, _auth = _hc3()
    if base is None:
        return None, "no HC3 configured (the .env chain) — set HC3_URL"
    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _CACHE_ROOT / "generated.lua"
    path.write_text(code, encoding="utf-8")
    try:
        fqa, _ = build_fqa(str(path), dist=False)
    except (FileNotFoundError, ValueError) as exc:
        return None, str(exc)
    remote = Hc3Remote(base, user, password, None)
    filename = f"{sanitize_filename(str(fqa.get('name') or 'QuickApp'))}.fqa"
    try:
        device, status = remote.multipart(
            "POST",
            "/quickApp/import",
            fields=[],
            files=[("file", filename, json.dumps(fqa, ensure_ascii=False))],
        )
    except OSError as exc:
        return None, f"cannot reach the HC3: {exc}"
    if status not in (200, 201) or not isinstance(device, dict):
        return None, f"cannot upload QA to the HC3 (HTTP {status})"
    return device, None


def serve_builder(port: int) -> BuilderServer:
    base, _user, _password, auth = _hc3()
    return BuilderServer(port, base, auth)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--port",
        type=int,
        default=8096,
        help="local port (default 8096; 0 = pick a free one)",
    )


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    try:
        server = serve_builder(args.port)
    except OSError as exc:
        print(f"builder: cannot bind a port near {args.port}: {exc}", file=sys.stderr)
        return 1
    _host, port = server.server_address[:2]
    note = "" if args.port in (0, port) else f" (port {args.port} was in use)"
    print(f"QA builder: http://127.0.0.1:{port}/{note}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0
