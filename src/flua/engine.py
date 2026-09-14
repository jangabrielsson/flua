"""Core flua engine: lupa VM + asyncio pump + message queues.

Single-entry discipline
-----------------------
The Lua VM is entered from exactly one place — the pump task's call to
``_PY.dispatch(batch)`` — and never while Lua code is on the stack. Lua ->
Python traffic is append-only (``_PY.post``), so a Python handler is never
asked to call back into Lua synchronously. This sidesteps lupa's reentrancy
constraints and keeps the message protocol transport-agnostic (every message
is JSON-compatible), so future asyncio work (HTTP, MQTT, threads) can plug
into the same queues.

Flow::

    Lua code  -> _PY.post(msg)         -> inbound deque
    pump      -> handler(msg)          -> side effects (timers, future I/O)
    handlers  -> enqueue_outbound(msg) -> outbound asyncio.Queue
    pump      -> _PY.dispatch(batch)   -> Lua handles results (timer fires)
"""

import asyncio
import contextlib
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import lupa

from . import messages
from .api import Api
from .api.state import public
from .bindings import install_bindings
from .clock import VirtualClock
from .config import parse_annotations, split_annotations
from .devices import catalog_types
from .environment import EnvChain
from .hc3 import Hc3Remote
from .http import http_call
from .mqtt import MqttPool
from .sync_socket import SyncTCPSockets, SyncUDPSockets
from .timers import TimerManager
from .websocket import WebSocketPool

logger = logging.getLogger(__name__)

# --%% directives that map directly onto device properties (local per QA)
_PROPERTY_DIRECTIVES = {
    "uid": "quickAppUuid",
    "description": "userDescription",
    "model": "model",
    "build": "buildNumber",
    "manufacturer": "manufacturer",
}

# .fqa export whitelist: the EXACT property set a real HC3 5.21x exports in
# a package (verified against a live export). Everything else is dynamic and
# must not travel.
_EXPORT_PROPERTIES = frozenset(
    {
        "viewLayout",
        "uiView",
        "useUiView",
        "uiCallbacks",
        "quickAppVariables",
        "typeTemplateInitialized",
        "userDescription",
    }
)

# Seconds the pump waits on the outbound queue before re-checking the inbound
# queue and the running flag. Upper bound on timer delivery latency.
_PUMP_POLL = 0.01

# Seconds the client waits on the HC3's refreshStates long poll: the HC3
# answers immediately with events and holds the request ~30s when idle.
# The request runs on a dedicated daemon thread (see _poll_once), never the
# default executor, so an abandoned poll can't delay Ctrl-C or exit —
# asyncio.run would otherwise wait for the executor worker at shutdown.
_HC3_POLL_TIMEOUT = 40.0


class LuaEngine:
    """Owns the lupa VM, the message queues, and the dispatch pump."""

    def __init__(
        self,
        start: float | None = None,
        speed: float = 1.0,
        config: dict[str, Any] | None = None,
        color: str = "auto",
        api_mode: str = "local",
        seed: dict[str, Any] | None = None,
    ) -> None:
        self._lua = lupa.LuaRuntime(unpack_returned_tuples=True, encoding="UTF-8")
        self._inbound: deque[dict[str, Any]] = deque()
        self._outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # Virtual time: 1 = realtime, N = accelerated, inf = instant (timers
        # fire immediately and virtual time jumps to their deadlines).
        self.clock = VirtualClock(speed)
        if start is not None:
            self.clock.set_start(start)
        # --%% annotations parsed from the script (exposed to Lua as _FLUA.config)
        self.config = config or {}
        # ANSI coloring for QA log lines: auto (tty only), always, never
        self._color = color
        self._timers = TimerManager(self.clock, self._on_timer_fired)
        # Blocking LuaSocket-compatible sockets for mobdebug (main-thread,
        # loop-freezing by design — see sync_socket.py).
        self.sync_sockets = SyncTCPSockets()
        self._running = False
        self._exit_code = 0
        self._pump_task: asyncio.Task[None] | None = None
        self.env = EnvChain()  # os.getenv chain: local .env > ~/.env > process env
        # HC3 REST API: the offline sim by default, the real HC3 with
        # --api remote (credentials from the environment chain).
        if api_mode is None:
            # no explicit flag: online when HC3 credentials are configured,
            # offline otherwise
            api_mode = "remote" if self._hc3_configured() else "local"
        if api_mode != "local":
            base_url = self.env.get("HC3_URL")
            host = self.env.get("HC3_HOST")
            if not base_url and host:
                base_url = f"http://{host}/"
            if not base_url:
                raise ValueError("--api remote requires HC3_URL (or HC3_HOST) in the environment")
            self.hc3 = Hc3Remote(
                base_url,
                user=self.env.get("HC3_USER"),
                password=self.env.get("HC3_PASSWORD"),
                pin=self.env.get("HC3_PIN"),
                on_auth_error=self._on_hc3_auth_error,
            )
        else:
            self.hc3 = None
        self.api = Api(self, seed)
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            messages.SET_TIMEOUT: self._handle_set_timeout,
            messages.HTTP_REQUEST: self._handle_http_request,
            messages.TCP_CONNECT: self._handle_tcp_connect,
            messages.TCP_SEND: self._handle_tcp_send,
            messages.TCP_READ: self._handle_tcp_read,
            messages.UDP_SEND: self._handle_udp_send,
            messages.UDP_RECEIVE: self._handle_udp_receive,
            messages.WS_CONNECT: self._handle_ws_connect,
            messages.WS_SEND: self._handle_ws_send,
            messages.MQTT_CONNECT: self._handle_mqtt_connect,
            messages.MQTT_SUBSCRIBE: self._handle_mqtt_subscribe,
            messages.MQTT_UNSUBSCRIBE: self._handle_mqtt_unsubscribe,
            messages.MQTT_PUBLISH: self._handle_mqtt_publish,
            messages.MQTT_DISCONNECT: self._handle_mqtt_disconnect,
            messages.CLEAR_TIMEOUT: self._handle_clear_timeout,
            messages.QA_VARS: self._handle_qa_vars,
            messages.LOG: self._handle_log,
            messages.EXIT: self._handle_exit,
            messages.QA_LOADED: self._handle_qa_loaded,
        }
        self._next_qa_id = 5000  # engine-assigned QA ids start at 5000
        self._qas: dict[int, dict[str, Any]] = {}  # QA directory (engine-owned)
        # temp files backing loadQAfromString QAs; deleted once the QA loads
        self._temp_qa_paths: set[str] = set()
        self._qa_file_dirs: set[str] = set()  # temp dirs for api-managed QA files
        # in-flight net.HTTPClient tasks: they count as pending work, so the
        # CLI keeps running until responses are delivered
        self._http_tasks: set[asyncio.Task[None]] = set()
        # net.TCPSocket ops run in worker threads over their own pool (the
        # debugger's sockets stay single-threaded on the main thread)
        self.qa_sockets = SyncTCPSockets()
        self.qa_udp = SyncUDPSockets()
        self.qa_websockets = WebSocketPool(self._on_ws_event)
        self._loop: asyncio.AbstractEventLoop | None = None
        self.qa_mqtt = MqttPool(self._on_mqtt_event)
        install_bindings(self)
        # .flua.lua (local > home > legacy ~/.plua/config.lua)
        self._load_lua_config()

    def _hc3_configured(self) -> bool:
        base = self.env.get("HC3_URL") or self.env.get("HC3_HOST")
        return bool(base)

    def qa_is_offline(self, qa_id: int | None) -> bool:
        """--%%offline:true on a QA pins its api.* calls to the sim."""
        if qa_id is None:
            return False
        info = self._qas.get(int(qa_id))
        return bool(info and info.get("config", {}).get("offline"))

    def _keep_alive_active(self) -> bool:
        """Any loaded QA with --%%keep-alive:true that hasn't exited keeps the
        online engine (and the HC3 poller's long poll) alive past idle — like
        a QA on the real HC3, which runs forever. Offline there is no poller
        to feed, so the directive has no effect there."""
        if self.hc3 is None:
            return False
        return any(
            info.get("loaded")
            and info.get("exited") is None
            and bool(info.get("config", {}).get("keep-alive"))
            for info in self._qas.values()
        )

    @staticmethod
    def _find_lua_config() -> Path | None:
        for path in (
            Path.cwd() / ".flua.lua",
            Path.home() / ".flua.lua",
            Path.home() / ".plua" / "config.lua",
        ):
            if path.exists():
                return path
        return None

    def _load_lua_config(self) -> None:
        """Load the Lua config file into the Lua state as _FLUA.configFile.
        Per-QA configs merge it at bootstrap (the file is the base, --%%
        annotations win). The file must ``return { ... }`` — a bare table
        is not a valid Lua chunk."""
        path = self._find_lua_config()
        if path is None:
            return
        source = path.read_text(encoding="utf-8")
        try:
            table = self._lua.execute(source)
        except Exception as exc:
            raise ValueError(f"error in Lua config {path}: {exc}") from exc
        if lupa.lua_type(table) != "table":
            raise ValueError(f"Lua config {path} must return a table")
        self._lua.globals()["_FLUA"]["configFile"] = table

    # -- bridge surface (used by bindings.py) ---------------------------------

    def post(self, msg: dict[str, Any]) -> None:
        """Append a Lua -> Python message. Never blocks, never calls Lua."""
        self._inbound.append(msg)

    def log_line(self, level: str, text: str) -> None:
        """Print a QA log line directly (safe at any call depth: only stdout
        and logging, never Lua state — so it works inside debugger-stepped
        code, where the pump is frozen)."""
        self._handle_log({"type": messages.LOG, "level": level, "text": text})

    def enqueue_outbound(self, msg: dict[str, Any]) -> None:
        """Queue a Python -> Lua message for the pump to deliver."""
        self._outbound.put_nowait(msg)

    def lua_runtime(self) -> lupa.LuaRuntime:
        return self._lua

    def lua_version(self) -> str:
        """The Lua interpreter version string (e.g. "Lua 5.4")."""
        return self._lua.execute("return _VERSION")

    def execute(self, lua_code: str) -> Any:
        """Execute Lua code synchronously at the top level.

        Only call when Lua is not on the stack (CLI bootstrap, tests). All
        runtime traffic must go through the queues.
        """
        return self._lua.execute(lua_code)

    def set_lua_global(self, name: str, value: Any) -> None:
        self._lua.globals()[name] = value

    def start_qa(
        self,
        path: str | None,
        code: str | None,
        qa_config: dict[str, Any],
        arg0: str,
    ) -> int:
        """Load a QuickApp in its own sandboxed environment.

        The QA runs as a tracked 0 ms timer inside a per-QA environment
        (isolated globals, per-QA timer tracking); see the QA section of
        lua/init.lua. ``path`` (loadfile) or ``code`` (load) is the QA body.

        Returns the QA id assigned by the engine — unique within this run,
        starting at 5000 and incrementing per QA.
        """
        qa_id = self._prepare_qa(path, code, qa_config, arg0)
        cfg = self._lua.table_from(self._qas[qa_id]["config"], recursive=True)
        arg = self._lua.table()
        arg[0] = arg0
        flua = self._lua.globals()["_FLUA"]
        if path is not None:
            flua["startQaFile"](qa_id, path, cfg, arg)
        else:
            flua["startQaCode"](qa_id, code, cfg, arg)
        return qa_id

    def _prepare_qa(
        self,
        path: str | None,
        code: str | None,
        qa_config: dict[str, Any],
        arg0: str,
    ) -> int:
        """Assign a QA id, resolve its name, register it in the sim directory."""
        qa_id = self._next_qa_id
        self._next_qa_id += 1
        qa_config = dict(qa_config)
        name = qa_config.get("name")
        if name is None:
            # names need not be unique: config name, else the script's
            # basename without path/suffix, else QA<id>
            name = Path(arg0).stem if arg0.endswith(".lua") else f"QA{qa_id}"
            qa_config["name"] = name
        self._normalize_files(qa_config)
        # Device properties: skeleton defaults < --%%properties < --%%property
        # and the named directives (--%%uid/description/model/build/
        # manufacturer), which map onto the device's properties directly.
        device_properties = dict(qa_config.get("properties") or {})
        device_properties.update(qa_config.get("property") or {})
        for directive, prop in _PROPERTY_DIRECTIVES.items():
            if qa_config.get(directive) is not None:
                device_properties[prop] = qa_config[directive]
        if path is not None:
            # --%%file paths resolve relative to the main file's directory
            base = Path(path).parent
            for entry in qa_config.get("files") or []:
                if entry.get("path") and not Path(entry["path"]).is_absolute():
                    entry["path"] = str(base / entry["path"])
        self._qas[qa_id] = {
            "name": name,
            "path": path,
            "code": code,
            "loaded": False,
            "type": qa_config.get("type"),
            "properties": device_properties,
            "config": qa_config,  # resolved copy (name/type/properties filled in)
        }
        self._qas[qa_id]["files"] = self._build_files(path, code, qa_config)
        # Register the QA as a device before its code runs: on the HC3 the
        # plugin device exists before onInit executes, and onInit's own api
        # calls (internalStorage, updateProperty) must find it.
        self.api.register_qa(qa_id, name, qa_config.get("type"), device_properties)
        return qa_id

    @staticmethod
    def _normalize_files(config: dict[str, Any]) -> list[dict[str, str]]:
        """--%%file:path,name entries -> ordered [{name, path}] (config["files"])."""
        raw = config.pop("file", None)
        entries: list[dict[str, str]] = []
        if raw is not None:
            if not isinstance(raw, list):
                raw = [raw]
            for spec in raw:
                path, _, name = str(spec).partition(",")
                path = path.strip()
                name = name.strip() or (Path(path).name if path else "")
                entries.append({"name": name, "path": path})
        config["files"] = entries
        return entries

    @staticmethod
    def _read_source(path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("cannot read QA file %s: %s", path, exc)
            return ""

    def _build_files(
        self, path: str | None, code: str | None, config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Full file list (main first): {name, path, isMain, type, source}."""
        if path is not None:
            files: list[dict[str, Any]] = [
                {
                    # HC3 has no file paths: the main file is named "main";
                    # the disk path stays internal (engine directory only)
                    "name": "main",
                    "path": str(path),
                    "isMain": True,
                    "type": "lua",
                    "source": self._read_source(str(path)),
                }
            ]
        else:
            files = [
                {
                    "name": "main",
                    "path": "",
                    "isMain": True,
                    "type": "lua",
                    "source": code or "",
                }
            ]
        for entry in config.get("files") or []:
            source = self._read_source(entry["path"]) if entry.get("path") else ""
            files.append(
                {
                    "name": entry["name"],
                    "path": entry.get("path") or "",
                    "isMain": False,
                    "type": "lua",
                    "source": source,
                }
            )
        return files

    # -- dynamic loading (loadQAfromFile / loadQAfromString) ----------------------

    def load_qa_file(self, path: str) -> tuple[int | None, str | None]:
        """Install and run a QA from a file — callable from running QA code.

        Reads the file's ``--%%`` annotations like the CLI (they win over the
        engine config; global params stay local to the loaded QA — a test QA
        must not change the running engine's clock). The bootstrap is queued
        as a ``startQA`` message so the pump runs it with no Lua on the
        stack, and it boots eagerly so follow-up calls from the same callback
        already reach the new QA. Returns (qa_id, None) or (None, error).
        """
        path = str(Path(path))
        try:
            source = Path(path).read_text(encoding="utf-8")
            global_params, local_params = split_annotations(parse_annotations(source))
        except Exception as exc:  # missing file, bad encoding, ...
            return None, str(exc)
        config = dict(self.config)
        config.update(global_params)
        config.update(local_params)
        qa_id = self._prepare_qa(path, None, config, path)
        resolved = self._qas[qa_id]["config"]  # files normalized inside _prepare_qa
        self.enqueue_outbound(messages.start_qa_msg(qa_id, path, resolved, path))
        return qa_id, None

    def qa_temp_file(self, code: str) -> str:
        """Write inline QA code to a temp file (deleted once the QA loads)."""
        directory = tempfile.mkdtemp(prefix="flua-qa-")
        path = os.path.join(directory, "qa.lua")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(code)
        self._temp_qa_paths.add(path)
        return path

    def _cleanup_temp_qa(self, path: str) -> None:
        self._temp_qa_paths.discard(path)
        with contextlib.suppress(OSError):
            Path(path).unlink()
            Path(path).parent.rmdir()

    # -- quickApp files API (multi-file QAs + .fqa export) -----------------------

    def _on_hc3_auth_error(self, status: int, url: str) -> None:
        """The HC3 locks after 4 failed credential attempts — abort NOW and
        never retry (this fires from the synchronous remote dispatch)."""
        message = (
            f"HC3 authentication failed (HTTP {status} for {url}): "
            "check HC3_USER/HC3_PASSWORD in the environment — flua exits "
            "immediately, the HC3 locks itself after 4 wrong attempts."
        )
        logger.error(message)
        self._exit_code = 1
        self._running = False

    def _poll_once(
        self, query: dict[str, str], timeout: float
    ) -> "asyncio.Future[tuple[Any, int]]":
        """One blocking refreshStates request on a dedicated daemon thread.

        The default executor would be joined by asyncio.run at shutdown, so an
        abandoned long poll (Ctrl-C, engine stop) would delay exit by up to its
        full timeout. Daemon threads are never joined: the process always
        leaves at once, and a cancelled poll simply drops its result.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[tuple[Any, int]] = loop.create_future()

        def worker() -> None:
            # Hc3Remote.request never raises (transport errors -> (None, 0));
            # its 401/403 auth guard fires inside request, from this thread.
            result = self.hc3.request("GET", "/refreshStates", query, None, timeout)
            try:
                loop.call_soon_threadsafe(self._deliver_poll_result, fut, result)
            except RuntimeError:
                pass  # loop already closed — the process is exiting

        threading.Thread(target=worker, name="flua-hc3-poll", daemon=True).start()
        return fut

    @staticmethod
    def _deliver_poll_result(
        fut: "asyncio.Future[tuple[Any, int]]", result: tuple[Any, int]
    ) -> None:
        if not fut.done():  # cancelled/abandoned polls drop their result
            fut.set_result(result)

    async def _hc3_poll(self) -> None:
        """Long-poll the real HC3's refreshStates (online mode) and mirror
        incoming events into the local buffer + the Lua
        RefreshStateSubscribers. The HC3 returns immediately with events, or
        after ~30s idle — then we simply retry."""
        while self._running:
            try:
                query = {} if self._hc3_last is None else {"last": self._hc3_last}
                data, status = await self._poll_once(query, _HC3_POLL_TIMEOUT)
                if status in (401, 403):
                    # the auth guard has aborted the engine — stop polling
                    # immediately: every retry is another attempt against the
                    # HC3's 4-attempt lockout budget
                    break
                if status == 200 and isinstance(data, dict):
                    self._hc3_last = int(data.get("last") or self._hc3_last)
                    for entry in data.get("events") or []:
                        self._mirror_event(entry)
                    for entry in data.get("changes") or []:
                        self._mirror_change(entry)
            except Exception as exc:
                logger.debug("hc3 refreshStates poll failed: %s", exc)
                await asyncio.sleep(5)
            # keep the retry tight; the HC3 itself holds the long poll open
            await asyncio.sleep(1)

    def _mirror_event(self, entry: dict[str, Any]) -> None:
        """Into the local buffer (merged api.get feed) + the pump-delivered
        subscriber message."""
        self.api.state.mirror_event(entry)
        self.enqueue_outbound(messages.refresh_state_event(entry))

    def _mirror_change(self, entry: dict[str, Any]) -> None:
        self.api.state.mirror_change(entry)

    def restart_qa(self, qa_id: int) -> None:
        """Re-run a QA's code (after a file change). Timers are cancelled,
        sources re-read from disk, and the new code boots via the pump.
        Device entry and variables persist — like an HC3 restart."""
        info = self._qas.get(int(qa_id))
        if info is None:
            raise ValueError(f"unknown QA {qa_id}")
        info["files"] = self._build_files(info["path"], info["code"], info["config"])
        self._timers.cancel_qa(int(qa_id))
        self.enqueue_outbound(
            messages.restart_qa_msg(
                int(qa_id), info["path"] or "", info["config"], info["path"] or ""
            )
        )

    def _qa_file_dir(self, qa_id: int) -> str:
        base = os.path.join(tempfile.gettempdir(), f"flua-qa-files-{os.getpid()}")
        directory = os.path.join(base, str(qa_id))
        os.makedirs(directory, exist_ok=True)
        self._qa_file_dirs.add(base)
        return directory

    @staticmethod
    def _safe_file_name(name: str) -> str:
        safe = os.path.basename(str(name)).strip()
        if not safe or safe in (".", ".."):
            raise ValueError(f"bad file name: {name!r}")
        return safe

    def qa_file_list(self, qa_id: int) -> list[dict[str, Any]] | None:
        """Public (metadata-only) view of a QA's files, main first."""
        info = self._qas.get(int(qa_id))
        if info is None:
            return None
        return [
            {"name": f["name"], "type": f["type"], "isMain": f["isMain"], "isOpen": False}
            for f in info["files"]
        ]

    def qa_file_get(self, qa_id: int, name: str) -> dict[str, Any] | None:
        info = self._qas.get(int(qa_id))
        if info is None:
            return None
        entry = next((f for f in info["files"] if f["name"] == name), None)
        if entry is None:
            return None
        return {
            "name": entry["name"],
            "type": entry["type"],
            "isMain": entry["isMain"],
            "isOpen": False,
            "content": entry["source"],
        }

    def qa_file_put(self, qa_id: int, name: str, content: str) -> dict[str, Any] | None:
        """Create/update a QA file (on disk in a temp dir) and restart the QA."""
        info = self._qas.get(int(qa_id))
        if info is None:
            return None
        safe = self._safe_file_name(name)
        entry = next((f for f in info["files"] if f["name"] == safe), None)
        if entry is None:
            path = os.path.join(self._qa_file_dir(int(qa_id)), safe)
            entry = {"name": safe, "path": path, "isMain": False, "type": "lua", "source": ""}
            info["files"].append(entry)
            info["config"]["files"] = info["config"].get("files") or []
            info["config"]["files"].append({"name": safe, "path": path})
        with open(entry["path"], "w", encoding="utf-8") as handle:
            handle.write(content)
        entry["source"] = content
        self.restart_qa(int(qa_id))
        return self.qa_file_get(int(qa_id), safe)

    def qa_file_delete(self, qa_id: int, name: str) -> bool:
        info = self._qas.get(int(qa_id))
        if info is None:
            return False
        entry = next((f for f in info["files"] if f["name"] == name), None)
        if entry is None or entry["isMain"]:
            return False
        info["files"].remove(entry)
        info["config"]["files"] = [
            f for f in info["config"].get("files") or [] if f["name"] != name
        ]
        with contextlib.suppress(OSError):
            Path(entry["path"]).unlink()
        self.restart_qa(int(qa_id))
        return True

    def qa_file_post(
        self, qa_id: int, name: str, file_type: str = "lua", content: str = ""
    ) -> dict[str, Any] | None:
        """POST /quickApp/{id}/files: create a file (empty by default), restart."""
        return self.qa_file_put(qa_id, name, content or "")

    def qa_files_put(
        self, qa_id: int, details: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        """PUT /quickApp/{id}/files: update several files, restart once."""
        info = self._qas.get(int(qa_id))
        if info is None:
            return None
        for entry in details:
            if isinstance(entry, dict) and entry.get("name") and entry.get("content") is not None:
                self.qa_file_put(qa_id, str(entry["name"]), str(entry["content"]))
        return self.qa_file_list(int(qa_id))

    def qa_available_types(self) -> list[dict[str, str]]:
        """GET /quickApp/availableTypes: the device catalog as {type, label}."""
        return [{"type": t, "label": t} for t in catalog_types()]

    def create_qa(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """POST /quickApp: create a QuickApp device (empty main) with the
        request's initial properties/interfaces/view/roomId."""
        if not isinstance(request, dict) or not request.get("name"):
            return None
        base = os.path.join(tempfile.gettempdir(), f"flua-qa-files-{os.getpid()}")
        os.makedirs(base, exist_ok=True)
        self._qa_file_dirs.add(base)
        directory = tempfile.mkdtemp(prefix="create-", dir=base)
        header = [f"--%%name:{request['name']}"]
        if request.get("type"):
            header.append(f"--%%type:{request['type']}")
        main_path = os.path.join(directory, "main.lua")
        with open(main_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(header) + "\n")
        qa_id, err = self.load_qa_file(main_path)
        if err is not None or qa_id is None:
            return None
        device = self.api.state.devices[qa_id]
        initial = request.get("initialProperties")
        if isinstance(initial, dict):
            device.setdefault("properties", {}).update(dict(initial))
        for interface in request.get("initialInterfaces") or []:
            if interface != "quickApp" and interface not in device.get("interfaces", []):
                device["interfaces"].append(interface)
        if request.get("roomId") is not None:
            device["roomID"] = int(request["roomId"])
        if isinstance(request.get("initialView"), dict):
            device["view"] = dict(request["initialView"])
        return public(device)

    def qa_export(self, qa_id: int) -> dict[str, Any] | None:
        """Export a QA as .fqa JSON — the real HC3 package shape:
        {name, type (device type), apiVersion, initialProperties, files}.

        Only whitelisted properties travel: the system fills dynamic
        properties at device creation and a real HC3 rejects packages that
        carry them (the set plua verified against real HC3s)."""
        info = self._qas.get(int(qa_id))
        if info is None:
            return None
        device = self.api.state.devices.get(int(qa_id)) or {}
        properties = {
            key: value
            for key, value in (device.get("properties") or {}).items()
            if key in _EXPORT_PROPERTIES
        }
        # private (__-prefixed) UI callbacks never travel (plua behavior)
        callbacks = [
            c
            for c in (properties.get("uiCallbacks") or [])
            if not str(c.get("name", "")).startswith("__")
        ]
        properties["uiCallbacks"] = callbacks
        # the HC3 expects these five fields as JSON arrays, never objects
        for key in ("quickAppVariables", "uiView", "supportedDeviceRoles"):
            if key not in properties:
                continue  # filtered out by the whitelist (e.g. supportedDeviceRoles)
            value = properties.get(key)
            properties[key] = (
                list(value.values())
                if isinstance(value, dict)
                else (value if isinstance(value, list) else [])
            )
        interfaces = [i for i in (device.get("interfaces") or []) if i != "quickApp"]
        fqa = {
            "name": info["name"],
            "type": device.get("type") or "com.fibaro.binarySwitch",
            "apiVersion": "1.3",
            "initialProperties": properties,
            "initialInterfaces": interfaces,
            "files": [
                {
                    "name": f["name"],
                    "isMain": f["isMain"],
                    "isOpen": False,
                    "content": f["source"],
                }
                for f in info["files"]
            ],
        }
        return self._arrayify_fqa(fqa)

    @staticmethod
    def _arrayify_fqa(fqa: dict[str, Any]) -> dict[str, Any]:
        """The HC3's import rejects empty JSON objects where its schema declares
        arrays (empty Lua tables serialize ambiguously). Fix the known array
        paths — the template's sections.items is the one that bit: the catalog
        captured it as {}."""
        properties = fqa.get("initialProperties")
        if not isinstance(properties, dict):
            return fqa
        layout = properties.get("viewLayout")
        if isinstance(layout, dict):
            sections = ((layout.get("$jason") or {}).get("body") or {}).get("sections")
            if isinstance(sections, dict):
                items = sections.get("items")
                if isinstance(items, dict):
                    sections["items"] = list(items.values()) if items else []
                elif not isinstance(items, list):
                    sections["items"] = []
        return fqa

    def import_qa(self, fqa: dict[str, Any]) -> tuple[int | None, str | None]:
        """Install and run a QA from a .fqa package.

        The package is unpacked to Lua files in a temp dir and the generated
        main file carries --%% directives (name + --%%file entries), so the
        standard pipeline — annotation parsing, file normalization, startQA —
        loads it like any other QA. Returns (qa_id, None) or (None, error)."""
        files = fqa.get("files")
        if not isinstance(files, list) or not files:
            return None, "fqa package has no files"
        main = next((f for f in files if f.get("isMain") or f.get("name") == "main"), None)
        if main is None:
            return None, "fqa package has no main file"
        base = os.path.join(tempfile.gettempdir(), f"flua-qa-files-{os.getpid()}")
        os.makedirs(base, exist_ok=True)
        self._qa_file_dirs.add(base)
        directory = tempfile.mkdtemp(prefix="import-", dir=base)
        main_path, err = self.fqa_to_files(fqa, directory)
        if err is not None:
            return None, err
        qa_id, err = self.load_qa_file(main_path)
        if err is not None:
            return qa_id, err
        device = self.api.state.devices.get(qa_id) if qa_id is not None else None
        if device is not None:
            initial = fqa.get("initialProperties")
            if isinstance(initial, dict):
                device.setdefault("properties", {}).update(dict(initial))
            for interface in fqa.get("initialInterfaces") or []:
                if interface != "quickApp" and interface not in device.get("interfaces", []):
                    device["interfaces"].append(interface)
        return qa_id, None

    @staticmethod
    def _lua_scalar(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "nil"
        return str(value)

    def fqa_to_files(self, fqa: dict[str, Any], directory: str) -> tuple[str | None, str | None]:
        """Unpack a .fqa package into ``directory``: the generated main file
        carries --%% directives (name, type, files, scalar initialProperties),
        the extras keep their assigned names. The result loads as a normal
        flua project (this is also what import_qa uses internally)."""
        files = fqa.get("files")
        if not isinstance(files, list) or not files:
            return None, "fqa package has no files"
        main = next((f for f in files if f.get("isMain") or f.get("name") == "main"), None)
        if main is None:
            return None, "fqa package has no main file"
        header = [f"--%%name:{fqa.get('name') or 'QuickApp'}"]
        device_type = fqa.get("type")
        if device_type and device_type != "QuickApp":  # legacy marker: no type
            header.append(f"--%%type:{device_type}")
        initial = fqa.get("initialProperties")
        if isinstance(initial, dict):
            for key, value in initial.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    header.append(f"--%%property:{key}={self._lua_scalar(value)}")
        for entry in files:
            if entry is main:
                continue
            try:
                name = self._safe_file_name(str(entry.get("name") or ""))
            except ValueError as exc:
                return None, str(exc)
            path = os.path.join(directory, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(str(entry.get("content") or ""))
            header.append(f"--%%file:{name},{name}")
        header.append("-- --------------- EOH ---------------")
        main_path = os.path.join(directory, "main.lua")
        with open(main_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(header) + "\n" + str(main.get("content") or ""))
        return main_path, None

    # -- QA directory -----------------------------------------------------------

    def qa_ids(self) -> list[int]:
        """Ids of all QAs started, in start order."""
        return list(self._qas)

    def qa_info(self, qa_id: int) -> dict[str, Any] | None:
        """Directory entry for a QA: name, path/code, loaded flag."""
        return self._qas.get(qa_id)

    def qa_instance(self, qa_id: int) -> Any:
        """The QA's QuickApp instance (a lupa table proxy), or None."""
        return self._lua.globals()["_FLUA"]["qa"](qa_id)

    def qa_timer_count(self, qa_id: int) -> int:
        """Active timers attributed to a QA (engine-side, single source of truth)."""
        return self._timers.qa_timer_count(qa_id)

    # -- lifecycle --------------------------------------------------------------

    def limit_run(self, virtual_seconds: float) -> None:
        """Cap simulated time (fixed ``--run-for -N``, ``--%%maxhours``):
        timers whose deadline lies beyond this many virtual seconds never
        fire, so instant mode stops exactly at the limit instead of racing
        past it between CLI polls."""
        self.clock.rebase()  # startup wall time must not become virtual time
        self._timers.set_horizon(self.clock.time + virtual_seconds)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._running:
            return
        self._running = True
        self._pump_task = asyncio.create_task(self._pump(), name="flua-pump")
        if self.hc3 is not None:
            # online mode: mirror the real HC3's refreshStates feed
            self._hc3_last: int | None = None
            self._poller_task = asyncio.create_task(self._hc3_poll(), name="flua-hc3-poll")

    async def stop(self) -> None:
        self._running = False
        self._timers.stop()
        self.sync_sockets.close_all()
        if self._pump_task is not None:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
            self._pump_task = None
        if self.hc3 is not None and self._poller_task is not None:
            self._poller_task.cancel()
            self._poller_task = None
        for path in list(self._temp_qa_paths):
            self._cleanup_temp_qa(path)
        for task in list(self._http_tasks):
            task.cancel()
        self.qa_websockets.close_all()
        self.qa_mqtt.close_all()
        for base in list(self._qa_file_dirs):
            with contextlib.suppress(OSError):
                shutil.rmtree(base, ignore_errors=True)
        self._qa_file_dirs.clear()

    def is_running(self) -> bool:
        return self._running

    @property
    def exit_code(self) -> int:
        """Exit code requested by Lua via the ``exit`` message (0 = none yet)."""
        return self._exit_code

    def has_pending_work(self) -> bool:
        """True while timers, message queues, in-flight worker tasks, or a
        --%%keep-alive QA (online) exist."""
        return (
            self._timers.active_count() > 0
            or self._keep_alive_active()
            or bool(self._inbound)
            or not self._outbound.empty()
            or bool(self._http_tasks)
            or self.qa_websockets.active_count() > 0
            or self.qa_mqtt.active_count() > 0
        )

    # -- pump --------------------------------------------------------------------

    async def _pump(self) -> None:
        while self._running:
            self.clock.tick(time.monotonic())
            self._timers.fire_due()
            await self._drain_inbound()
            try:
                batch = [await asyncio.wait_for(self._outbound.get(), timeout=_PUMP_POLL)]
            except TimeoutError:
                continue
            while not self._outbound.empty():
                batch.append(self._outbound.get_nowait())
            self._deliver_to_lua(batch)

    async def _drain_inbound(self) -> None:
        while self._inbound:
            msg = self._inbound.popleft()
            handler = self._handlers.get(msg.get("type"))
            if handler is None:
                logger.warning("no handler for message type %r; dropped %r", msg.get("type"), msg)
                continue
            try:
                result = handler(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("handler %r failed for message %r", msg.get("type"), msg)

    def _deliver_to_lua(self, batch: list[dict[str, Any]]) -> None:
        """The single Python -> Lua entry point."""
        try:
            lua_batch = self._lua.table_from(batch, recursive=True)
            self._lua.globals()["_FLUA"]["dispatch"](lua_batch)
        except Exception:
            logger.exception("lua dispatch failed for batch %r", batch)

    # -- handlers (Lua -> Python message types) -----------------------------------

    def _handle_set_timeout(self, msg: dict[str, Any]) -> None:
        self._timers.set_timeout(int(msg["id"]), int(msg["delay"]), msg.get("qa"))

    def _handle_qa_vars(self, msg: dict[str, Any]) -> None:
        """Merge evaluated --%%var values into the QA device's variables."""
        device = self.api.state.devices.get(int(msg["id"]))
        if device is None:
            return
        properties = device.setdefault("properties", {})
        existing = properties.get("quickAppVariables")
        if not isinstance(existing, list):
            existing = []
        merged = {v.get("name"): v for v in existing if isinstance(v, dict) and v.get("name")}
        for name, value in (msg.get("vars") or {}).items():
            if str(name) not in merged:  # initializers never clobber runtime state
                merged[str(name)] = {"name": str(name), "value": value}
        properties["quickAppVariables"] = list(merged.values())

    def _handle_http_request(self, msg: dict[str, Any]) -> None:
        """Run a net.HTTPClient request in a worker thread (never blocks the pump)."""
        logger.debug("http request id=%s %s %s", msg["id"], msg.get("method"), msg["url"])
        task = asyncio.create_task(self._run_http_request(msg), name="flua-http")
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    # -- net.TCPSocket (worker threads over the dedicated qa_sockets pool) ------

    def _spawn_tcp(self, msg: dict[str, Any], kind: str, func: Any, *args: Any) -> None:
        logger.debug("tcp %s id=%s", msg["type"], msg["id"])
        task = asyncio.create_task(self._run_tcp_op(msg, kind, func, *args), name="flua-tcp")
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    def _handle_tcp_connect(self, msg: dict[str, Any]) -> None:
        self._spawn_tcp(
            msg,
            "connect",
            self.qa_sockets.connect,
            str(msg["host"]),
            int(msg["port"]),
            float(msg.get("timeout") or 1.0),
        )

    def _handle_tcp_send(self, msg: dict[str, Any]) -> None:
        self._spawn_tcp(
            msg, "send", self.qa_sockets.write, int(msg["conn"]), str(msg.get("data") or "")
        )

    def _handle_tcp_read(self, msg: dict[str, Any]) -> None:
        conn = int(msg["conn"])
        if msg.get("delimiter") is not None:
            self._spawn_tcp(msg, "read", self.qa_sockets.read_until, conn, str(msg["delimiter"]))
        elif msg.get("pattern") == "*l":
            self._spawn_tcp(msg, "read", self.qa_sockets.read, conn, "*l")
        elif msg.get("pattern") == "*a":
            self._spawn_tcp(msg, "read", self.qa_sockets.read, conn, "*a")
        else:
            # HC3's read() returns the next available data package: one recv
            self._spawn_tcp(msg, "read", self.qa_sockets.read_chunk, conn)

    async def _run_tcp_op(self, msg: dict[str, Any], kind: str, func: Any, *args: Any) -> None:
        try:
            result = await asyncio.to_thread(func, *args)
        except Exception as exc:
            result = (False, f"tcp: {exc}")
        ok = bool(result[0])
        value = result[1] if len(result) > 1 else None
        if kind == "connect":
            out = messages.tcp_result(
                msg["id"], msg.get("qa"), ok, conn=value if ok else None, err=None if ok else value
            )
        elif kind == "send":
            out = messages.tcp_result(msg["id"], msg.get("qa"), ok, err=None if ok else value)
        else:
            out = messages.tcp_result(
                msg["id"], msg.get("qa"), ok, data=value if ok else None, err=None if ok else value
            )
        self.enqueue_outbound(out)

    # -- net.UDPSocket (worker threads over the dedicated qa_udp pool) ---------

    def _handle_udp_send(self, msg: dict[str, Any]) -> None:
        logger.debug("udp %s id=%s", msg["type"], msg["id"])
        task = asyncio.create_task(
            self._run_udp_op(
                msg,
                self.qa_udp.send_to,
                int(msg["conn"]),
                str(msg.get("data") or ""),
                str(msg["ip"]),
                int(msg["port"]),
            ),
            name="flua-udp",
        )
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    def _handle_udp_receive(self, msg: dict[str, Any]) -> None:
        logger.debug("udp %s id=%s", msg["type"], msg["id"])
        task = asyncio.create_task(
            self._run_udp_op(msg, self.qa_udp.receive, int(msg["conn"])),
            name="flua-udp",
        )
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    async def _run_udp_op(self, msg: dict[str, Any], func: Any, *args: Any) -> None:
        try:
            result = await asyncio.to_thread(func, *args)
        except Exception as exc:
            result = (False, f"udp: {exc}")
        ok = bool(result[0])
        value = result[1] if len(result) > 1 else None
        out = messages.udp_result(
            msg["id"], msg.get("qa"), ok, data=value if ok else None, err=None if ok else value
        )
        self.enqueue_outbound(out)

    # -- net.WebSocketClient (RFC 6455 client in worker threads) ---------------

    def _handle_ws_connect(self, msg: dict[str, Any]) -> None:
        logger.debug("ws connect conn=%s url=%s", msg["conn"], msg["url"])
        task = asyncio.create_task(self._run_ws_connect(msg), name="flua-ws")
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    async def _run_ws_connect(self, msg: dict[str, Any]) -> None:
        conn = int(msg["conn"])
        ok, err = await asyncio.to_thread(
            self.qa_websockets.connect,
            conn,
            str(msg["url"]),
            float(msg.get("timeout") or 10.0),
        )
        if not ok:
            self._on_ws_event(conn, "error", err)
            return
        self._on_ws_event(conn, "connected", None)
        self.qa_websockets.start_receiver(conn)

    def _handle_ws_send(self, msg: dict[str, Any]) -> None:
        logger.debug("ws send conn=%s", msg["conn"])
        task = asyncio.create_task(
            self._run_ws_send(msg, int(msg["conn"]), str(msg.get("data") or "")),
            name="flua-ws",
        )
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    async def _run_ws_send(self, msg: dict[str, Any], conn: int, data: str) -> None:
        ok, err = await asyncio.to_thread(self.qa_websockets.send, conn, data)
        if not ok:
            self._on_ws_event(conn, "error", err)

    def _on_ws_event(self, conn: int, event: str, data: Any) -> None:
        """Event sink for WsClient receiver threads (any thread)."""
        qa = self.qa_websockets.qa_of(conn)
        if qa is None:
            return
        out = messages.ws_event(qa, conn, event, data)
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is not None and running is not loop:
            loop.call_soon_threadsafe(self.enqueue_outbound, out)  # worker thread
        else:
            self.enqueue_outbound(out)

    # -- mqtt.* client (MQTT 3.1.1 in worker threads) ---------------------------

    def _spawn_mqtt_op(self, msg: dict[str, Any], func: Any, *args: Any) -> None:
        task = asyncio.create_task(self._run_mqtt_op(msg, func, *args), name="flua-mqtt")
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    async def _run_mqtt_op(self, msg: dict[str, Any], func: Any, *args: Any) -> None:
        try:
            ok, err = await asyncio.to_thread(func, *args)
        except Exception as exc:
            ok, err = False, str(exc)
        conn = int(msg["conn"])
        if ok:
            self._on_mqtt_event(
                conn, "opDone", {"kind": msg["type"], "packetId": msg.get("packetId"), "code": 0}
            )
        else:
            self._on_mqtt_event(
                conn,
                "opDone",
                {"kind": msg["type"], "packetId": msg.get("packetId"), "code": -1, "message": err},
            )

    def _handle_mqtt_connect(self, msg: dict[str, Any]) -> None:
        conn = int(msg["conn"])
        options = dict(msg.get("options") or {})

        async def run() -> None:
            ok, err = await asyncio.to_thread(
                self.qa_mqtt.connect,
                conn,
                str(msg["uri"]),
                options,
                float(options.get("timeout") or 10.0),
            )
            if not ok:
                self._on_mqtt_event(conn, "connectDone", {"code": -1, "message": err})
                return
            self._on_mqtt_event(conn, "connectDone", {"code": 0})
            self.qa_mqtt.start_receiver(conn)

        task = asyncio.create_task(run(), name="flua-mqtt")
        self._http_tasks.add(task)
        task.add_done_callback(self._http_tasks.discard)

    def _handle_mqtt_subscribe(self, msg: dict[str, Any]) -> None:
        topics = [[str(t), int(q)] for t, q in (msg.get("topics") or [])]
        self._spawn_mqtt_op(
            msg, self.qa_mqtt.subscribe, int(msg["conn"]), int(msg["packetId"]), topics
        )

    def _handle_mqtt_unsubscribe(self, msg: dict[str, Any]) -> None:
        topics = [str(t) for t in (msg.get("topics") or [])]
        self._spawn_mqtt_op(
            msg, self.qa_mqtt.unsubscribe, int(msg["conn"]), int(msg["packetId"]), topics
        )

    def _handle_mqtt_publish(self, msg: dict[str, Any]) -> None:
        self._spawn_mqtt_op(
            msg,
            self.qa_mqtt.publish,
            int(msg["conn"]),
            int(msg["packetId"]),
            str(msg["topic"]),
            str(msg.get("payload") or ""),
            int(msg.get("qos") or 0),
            bool(msg.get("retain", False)),
        )

    def _handle_mqtt_disconnect(self, msg: dict[str, Any]) -> None:
        self._spawn_mqtt_op(msg, self.qa_mqtt.disconnect, int(msg["conn"]))

    def _on_mqtt_event(self, conn: int, event: str, data: Any) -> None:
        """Event sink for MqttClient receiver threads (any thread)."""
        qa = self.qa_mqtt.qa_of(conn)
        if qa is None:
            return
        out = messages.mqtt_event(qa, conn, event, data)
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is not None and running is not loop:
            loop.call_soon_threadsafe(self.enqueue_outbound, out)  # worker thread
        else:
            self.enqueue_outbound(out)

    async def _run_http_request(self, msg: dict[str, Any]) -> None:
        result: dict[str, Any]
        try:
            status, data, headers = await asyncio.to_thread(
                http_call,
                str(msg.get("method") or "GET"),
                str(msg["url"]),
                {str(k): str(v) for k, v in (msg.get("headers") or {}).items()},
                msg.get("data"),
                float(msg.get("timeout") or 30.0),
            )
            result = messages.http_result(msg["id"], msg.get("qa"), status, data, headers)
        except Exception as exc:
            result = messages.http_result(msg["id"], msg.get("qa"), error=str(exc))
        logger.debug("http result id=%s %s", msg["id"], result.get("status", result.get("error")))
        self.enqueue_outbound(result)

    def _handle_clear_timeout(self, msg: dict[str, Any]) -> None:
        self._timers.clear_timeout(int(msg["id"]))

    def _handle_log(self, msg: dict[str, Any]) -> None:
        level = str(msg.get("level", "info")).upper()
        text = str(msg.get("text", ""))
        logger.debug("Lua [%s]: %s", level, text)
        # colors (if enabled) are embedded in the text by the Lua side
        print(text, flush=True)

    def color_enabled(self) -> bool:
        """Whether QA log lines should carry ANSI colors.

        Consulted by the Lua log formatter via _PY.color_enabled.
        """
        if self._color == "always":
            return True
        if self._color == "never":
            return False
        return sys.stdout.isatty()

    def _handle_exit(self, msg: dict[str, Any]) -> None:
        code = int(msg.get("code", 0))
        if "qa" in msg:
            # HC3 semantics: exit() terminates the QA that called it (each QA
            # is its own process on the HC3; flua runs them cooperatively).
            # Cancel the QA's timers, record its exit, and keep the engine
            # running for the other QAs — the run loop stops it once no work
            # is left.
            qa_id = int(msg["qa"])
            self._timers.cancel_qa(qa_id)
            info = self._qas.get(qa_id)
            if info is not None:
                info["exited"] = code
                logger.debug("QA %d (%s) exited with code %d", qa_id, info["name"], code)
            if code != 0:
                self._exit_code = code  # last failing QA wins
            return
        self._exit_code = code
        self._running = False

    def _handle_qa_loaded(self, msg: dict[str, Any]) -> None:
        qa_id = int(msg["id"])
        info = self._qas.get(qa_id)
        if info is not None:
            info["loaded"] = True
            logger.debug("QA %d (%s) loaded", qa_id, info["name"])
            if info.get("path") in self._temp_qa_paths:
                # the temp file backing loadQAfromString was consumed
                self._cleanup_temp_qa(info["path"])

    # -- timer bridge ---------------------------------------------------------------

    def _on_timer_fired(self, timer_id: int) -> None:
        self.enqueue_outbound(messages.timer_expired(timer_id))

    def note_debugger_pause(self) -> None:
        """Freeze virtual time while the debugger waits (mobdebug yield hook)."""
        self.clock.note_pause()
