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
import contextlib
import http.server
import json
import os
import re
import sys
import tempfile
import threading
import time
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
_DEVNULL = open(os.devnull, "w", encoding="utf-8")  # QA logs go to files only

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


def _parse_wait(value: object) -> float:
    """A verify wait: a bare number (seconds) or '30s' / '2m' / '1h'."""
    if isinstance(value, (int, float)):
        return float(value)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|m|h)?", str(value or "").strip())
    if not match:
        raise ValueError(f"bad wait {value!r} (use seconds, 30s, 2m, 1h)")
    return float(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[match.group(2) or "s"]


async def _settle(engine: object, virtual_seconds: float) -> None:
    """Advance the virtual clock by at least ``virtual_seconds`` (wall-bound):
    the pump ticks the clock, so this waits real time until the virtual clock
    has covered the span — deterministic under any pump cadence, unlike a
    fixed wall sleep scaled by _SIM_SPEED. A wall cap keeps a drained pump
    from hanging the verify run."""
    start = engine.virtual_now()  # type: ignore[attr-defined]
    deadline = time.monotonic() + 5.0
    while engine.virtual_now() - start < virtual_seconds:  # type: ignore[attr-defined]
        if time.monotonic() > deadline:
            return
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.02)  # one extra pump pass: timers at the boundary fire


async def _run_verification(manifest: dict[str, object]) -> dict[str, object]:
    """Run a recipe's declared verify scenario in the sim: seed the params,
    drive the steps (device actions, weather, UI sliders, virtual waits),
    check the outcomes, and report step-by-step. The clock runs at _SIM_SPEED;
    every action settles ~30 virtual seconds, which also fires the recipes'
    30s polls — scenarios complete in a couple of wall seconds."""
    from ..engine import LuaEngine

    rid = str(manifest.get("id") or "?")
    scenario = manifest.get("verify")
    if not isinstance(scenario, dict) or not isinstance(scenario.get("steps"), list):
        return {"id": rid, "ok": False, "error": "no verify scenario in the manifest"}
    code = _recipe_code(rid)
    if code is None:
        return {"id": rid, "ok": False, "error": "recipe not found"}
    steps: list[dict[str, object]] = []
    with tempfile.NamedTemporaryFile(
        "w", prefix="flua-verify-", suffix=".log", delete=False, encoding="utf-8"
    ) as handle:
        log_path = Path(handle.name)
    try:
        engine = LuaEngine(speed=_SIM_SPEED, api_mode="local", log_stream=_DEVNULL)
        engine.set_log_mode("text", str(log_path))
        await engine.start()
        try:
            verify_params = scenario.get("params")
            run_code = bake_params(code, verify_params if isinstance(verify_params, dict) else {})
            params, seeded, _extra, seed_err = _seed_sim_devices(engine, run_code, manifest)
            if seed_err is not None:
                return {"id": rid, "ok": False, "error": seed_err}
            run_code = bake_params(run_code, params)
            qa_id, qa_err = engine.load_qa_file(engine.qa_temp_file(run_code))
            if qa_id is None:
                return {"id": rid, "ok": False, "error": qa_err or "cannot load the QA"}
            device_ids = {entry["name"]: entry["simId"] for entry in seeded}
            await _settle(engine, 30)  # the QA boots; the first 30s poll fires
            ok = True
            for step in scenario["steps"]:
                if not isinstance(step, dict):
                    steps.append({"passed": False, "detail": "bad step"})
                    ok = False
                    continue
                passed, detail = await _verify_step(engine, step, device_ids, qa_id, log_path)
                steps.append({"passed": passed, "detail": detail})
                if not passed:
                    ok = False
            log = log_path.read_text(encoding="utf-8")
            return {"id": rid, "ok": ok, "qa": qa_id, "steps": steps, "log": log}
        finally:
            await engine.stop()
    finally:
        log_path.unlink(missing_ok=True)


async def _verify_step(
    engine: object,
    step: dict[str, object],
    device_ids: dict[str, object],
    qa_id: int,
    log_path: Path,
) -> tuple[bool, str]:
    """One scenario step; device/slider/weather steps settle afterwards
    (~30 virtual seconds — the recipes' poll interval) so the reaction
    lands before the next check."""
    if "device" in step:
        name = str(step["device"])
        device_id = device_ids.get(name)
        if device_id is None:
            return False, f"{name}: not seeded (device param unset)"
        args = step.get("args")
        _data, status = engine.api.dispatch(  # type: ignore[attr-defined]
            "POST", f"/devices/{device_id}/action/{step['call']}", {"args": args or []}
        )
        await _settle(engine, 30)
        return status in (200, 201, 202, 204), f"{name}:{step['call']} -> {status}"
    if "slider" in step:
        engine.api.dispatch(  # type: ignore[attr-defined]
            "GET",
            f"/plugins/callUIEvent?deviceID={qa_id}&elementName={step['slider']}"
            f"&eventType=onChanged&value={step['value']}",
        )
        await _settle(engine, 30)
        return True, f"slider {step['slider']} -> {step['value']}"
    if "weather" in step:
        changes = step["weather"]
        engine.api.state.weather_overrides.update(changes)  # type: ignore[attr-defined]
        await _settle(engine, 30)
        return True, f"weather {changes}"
    if "wait" in step:
        try:
            seconds = _parse_wait(step["wait"])
        except ValueError as exc:
            return False, str(exc)
        await _settle(engine, seconds)
        return True, f"waited {seconds:g}s (virtual)"
    if "check" in step:
        check = step["check"]
        if isinstance(check, dict) and "device" in check:
            device_id = device_ids.get(str(check["device"]))
            dev = engine.api.state.devices.get(device_id) if device_id is not None else None  # type: ignore[attr-defined]
            actual = (dev or {}).get("properties", {}).get("value")
            expected = check["value"]
            passed = actual == expected
            return passed, f"{check['device']}.value == {expected!r} (got {actual!r})"
        if isinstance(check, dict) and "log" in check:
            text = log_path.read_text(encoding="utf-8")
            count = text.count(str(check["log"]))
            want = check.get("count", 1)
            passed = count == want if isinstance(want, int) else count >= 1
            return passed, f"log contains {check['log']!r} x{count} (want {want})"
        return False, "check needs device+value or log"
    return False, "step needs one of device/slider/weather/wait/check"


def _seed_sim_devices(
    engine: object, code: str, manifest: dict[str, object] | None
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], str | None]:
    """Load a bundled sim device for every picked (nonzero) device param —
    the bake params re-point the code at the sim ids, so the QA polls a real
    sim world instead of empty air — plus the recipe's declared simDevices
    (world devices the user drives from the view, like the weatherMgr).
    Returns (bake-params, seeded, extra, error)."""
    from ..engine import SIM_DEVICES_DIR

    params: dict[str, object] = {}
    seeded: list[dict[str, object]] = []
    extra: list[dict[str, object]] = []
    if not manifest:
        return params, seeded, extra, None
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
            return params, seeded, extra, f"sim device {kind}: {sim_err}"
        params[name] = sim_id
        seeded.append({"name": name, "kind": kind, "simId": sim_id})
    for name in manifest.get("simDevices") or []:
        if not isinstance(name, str) or not (SIM_DEVICES_DIR / f"{name}.lua").is_file():
            continue
        sim_id, sim_err = engine.load_sim_device(name)
        if sim_id is None:
            return params, seeded, extra, f"sim device {name}: {sim_err}"
        extra.append({"name": name, "kind": name, "simId": sim_id})
    return params, seeded, extra, None


async def _run_simulation(
    code: str, manifest: dict[str, object] | None, minutes: int, log_path: Path
) -> dict[str, object]:
    """Boot the generated QA in the offline sim and run it for ``minutes``
    virtual minutes (the clock runs 600x, so 1 wall second = 10 virtual
    minutes). Picked device ids are re-pointed at bundled sim devices of
    the matching kind, so the QA polls a real sim world instead of empty
    air. Returns {error, devices, virtualMinutes}; the log lands in
    log_path."""
    from ..engine import LuaEngine

    minutes = max(1, min(int(minutes or 5), 30))
    engine = LuaEngine(speed=_SIM_SPEED, api_mode="local", log_stream=_DEVNULL)
    engine.set_log_mode("text", str(log_path))
    qa_info: dict[str, object] | None = None
    extra: list[dict[str, object]] = []
    error: str | None = None
    await engine.start()
    try:
        params, seeded, extra, seed_err = _seed_sim_devices(engine, code, manifest)
        error = seed_err
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
        "simDevices": extra,
        "virtualMinutes": minutes,
        "qa": qa_info,
        "clock": clock,
    }


# the live UI session: one engine + viewer, kept running for the browser
# tab until the next View UI click or the builder exits. The engine pump
# and the viewer live on a dedicated asyncio loop in a daemon thread, so
# the builder's sync HTTP handler stays untouched.
_UI_LOCK = threading.Lock()
_UI_SESSION: dict[str, object] = {}


def _stop_ui_session() -> None:
    """Stop the live engine + viewer, if one is running. Idempotent."""
    with _UI_LOCK:
        session = dict(_UI_SESSION)
        _UI_SESSION.clear()
    loop = session.get("loop")
    if not isinstance(loop, asyncio.AbstractEventLoop):
        return

    async def _stop() -> None:
        server = session.get("server")
        engine = session.get("engine")
        if server is not None:
            with contextlib.suppress(Exception):
                await server.stop()  # type: ignore[attr-defined]
        if engine is not None:
            with contextlib.suppress(Exception):
                await engine.stop()  # type: ignore[attr-defined]

    try:
        asyncio.run_coroutine_threadsafe(_stop(), loop).result(timeout=10)
    except Exception:
        pass  # a broken session is dropped, not nursed
    loop.call_soon_threadsafe(loop.stop)


def _start_ui_session(
    code: str, manifest: dict[str, object] | None
) -> tuple[str, dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    """Boot the generated QA on a persistent engine and serve its web view.
    Returns (url, qa, seeded, extra); the last code wins — a new click
    replaces the previous session."""
    from ..engine import LuaEngine
    from ..http_server import ApiServer

    _stop_ui_session()
    loop = asyncio.new_event_loop()

    async def _start(
    ) -> tuple[object, object, int, list[dict[str, object]], list[dict[str, object]]]:
        engine = LuaEngine(api_mode="local", log_stream=_DEVNULL)
        await engine.start()
        try:
            params, seeded, extra, seed_err = _seed_sim_devices(engine, code, manifest)
            if seed_err is not None:
                raise RuntimeError(seed_err)
            run_code = bake_params(code, params) if params else code
            qa_path = engine.qa_temp_file(run_code)
            qa_id, qa_err = engine.load_qa_file(qa_path)
            if qa_id is None:
                raise RuntimeError(qa_err or "cannot load the QA")
            engine.qa_keep_alive(qa_id)
            server = ApiServer(engine.api, port=0)
            await server.start()
            engine.set_sim_api_port(server.port)
        except BaseException:
            await engine.stop()
            raise
        return engine, server, qa_id, seeded, extra

    threading.Thread(target=loop.run_forever, name="flua-builder-ui", daemon=True).start()
    try:
        engine, server, qa_id, seeded, extra = asyncio.run_coroutine_threadsafe(
            _start(), loop
        ).result(timeout=30)
    except BaseException:
        loop.call_soon_threadsafe(loop.stop)
        raise
    with _UI_LOCK:
        _UI_SESSION.update(engine=engine, server=server, loop=loop)
    qa = {"id": qa_id, "name": (manifest or {}).get("title") or "QuickApp"}
    return f"http://127.0.0.1:{server.port}/", qa, seeded, extra


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
        if parsed.path == "/api/viewui":
            rid = str(request.get("id") or "")
            code = request.get("code")
            if not isinstance(code, str) or not code.strip():
                self._json(400, {"error": "code is required"})
                return
            manifest = _manifest_for(rid) if re.fullmatch(r"[a-z0-9-]+", rid) else None
            try:
                url, qa, seeded, extra = _start_ui_session(code, manifest)
            except Exception as exc:
                self._json(502, {"error": str(exc)})
                return
            self._json(200, {"url": url, "qa": qa, "devices": seeded, "simDevices": extra})
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
            # a fresh log file per run: set_log_mode appends, so a shared
            # path would leak stale lines from earlier runs (and concurrent
            # simulations would interleave)
            with tempfile.NamedTemporaryFile(
                "w", prefix="flua-sim-", suffix=".log", delete=False, encoding="utf-8"
            ) as handle:
                log_path = Path(handle.name)
            try:
                result = asyncio.run(_run_simulation(code, manifest, minutes, log_path))
                try:
                    result["log"] = log_path.read_text(encoding="utf-8")
                except OSError:
                    result["log"] = ""
            finally:
                log_path.unlink(missing_ok=True)
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

    def server_close(self) -> None:
        _stop_ui_session()  # the viewer tab dies with the builder
        super().server_close()


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
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the installed recipe templates",
    )
    parser.add_argument(
        "--verify",
        metavar="ID",
        help="run a recipe's verify scenario in the sim (see --list)",
    )
    parser.add_argument(
        "--verify-all",
        action="store_true",
        help="run the verify scenarios of every recipe that declares one",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable output for --list and --verify (agents)",
    )


def _verify_all() -> dict[str, object]:
    """Run every declared verify scenario; returns the aggregate verdict
    (recipes without a scenario are listed as skipped, not failures)."""
    results: list[dict[str, object]] = []
    skipped: list[str] = []
    for recipe in cached_index().get("recipes", []):
        rid = str(recipe.get("id") or "")
        if isinstance(recipe.get("verify"), dict):
            results.append(asyncio.run(_run_verification(recipe)))
        else:
            skipped.append(rid)
    return {
        "ok": all(result["ok"] for result in results),
        "results": results,
        "skipped": skipped,
    }


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.list:
        index = cached_index()
        if args.json:
            print(json.dumps(index, indent=2, ensure_ascii=False))
            return 0
        for recipe in index.get("recipes", []):
            categories = ", ".join(recipe.get("categories") or [])
            suffix = f"  [{categories}]" if categories else ""
            print(f"{recipe.get('id')}  {recipe.get('title')}{suffix}")
        return 0
    if args.verify_all:
        verdict = _verify_all()
        if args.json:
            print(json.dumps(verdict, indent=2, ensure_ascii=False))
        else:
            for result in verdict["results"]:
                print(f"{result['id']}: {'OK' if result['ok'] else 'FAILED'}")
                if not result["ok"]:
                    for step in result.get("steps", []):
                        if not step["passed"]:
                            print(f"  [FAIL] {step['detail']}")
                    if result.get("error"):
                        print(f"  [FAIL] {result['error']}")
            if verdict["skipped"]:
                print("no scenario: " + ", ".join(verdict["skipped"]))
            print("all templates OK" if verdict["ok"] else "TEMPLATE VERIFICATION FAILED")
        return 0 if verdict["ok"] else 1
    if args.verify:
        manifest = _manifest_for(str(args.verify))
        if manifest is None:
            print(f"builder: unknown recipe {args.verify!r} (try --list)", file=sys.stderr)
            return 1
        result = asyncio.run(_run_verification(manifest))
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"verify {result['id']}")
            for step in result.get("steps", []):
                print(f"  [{'ok' if step['passed'] else 'FAIL'}] {step['detail']}")
            if result.get("error"):
                print(f"  [FAIL] {result['error']}")
            print(f"{result['id']}: {'OK' if result['ok'] else 'FAILED'}")
        return 0 if result["ok"] else 1
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
