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
import sys
import tempfile
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import lupa

from . import messages
from .api import Api
from .bindings import install_bindings
from .clock import VirtualClock
from .config import parse_annotations, split_annotations
from .http import http_call
from .sync_socket import SyncTCPSockets, SyncUDPSockets
from .timers import TimerManager

logger = logging.getLogger(__name__)

# Seconds the pump waits on the outbound queue before re-checking the inbound
# queue and the running flag. Upper bound on timer delivery latency.
_PUMP_POLL = 0.01


class LuaEngine:
    """Owns the lupa VM, the message queues, and the dispatch pump."""

    def __init__(
        self,
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
        # --%% annotations parsed from the script (exposed to Lua as _FLUA.config)
        self.config = config or {}
        # ANSI coloring for QA log lines: auto (tty only), always, never
        self._color = color
        self._timers = TimerManager(self.clock, self._on_timer_fired)
        # Blocking LuaSocket-compatible sockets for mobdebug (main-thread,
        # loop-freezing by design — see sync_socket.py).
        self.sync_sockets = SyncTCPSockets()
        # HC3 REST API: offline sim (running QAs + seeded state) today, the
        # remote HC3 later. Dispatch never blocks the pump.
        if api_mode != "local":
            raise ValueError(f"unsupported api mode {api_mode!r}: only 'local' is implemented")
        self.api = Api(self, seed)
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            messages.SET_TIMEOUT: self._handle_set_timeout,
            messages.HTTP_REQUEST: self._handle_http_request,
            messages.TCP_CONNECT: self._handle_tcp_connect,
            messages.TCP_SEND: self._handle_tcp_send,
            messages.TCP_READ: self._handle_tcp_read,
            messages.UDP_SEND: self._handle_udp_send,
            messages.UDP_RECEIVE: self._handle_udp_receive,
            messages.CLEAR_TIMEOUT: self._handle_clear_timeout,
            messages.LOG: self._handle_log,
            messages.EXIT: self._handle_exit,
            messages.QA_LOADED: self._handle_qa_loaded,
        }
        self._running = False
        self._exit_code = 0
        self._pump_task: asyncio.Task[None] | None = None
        self._next_qa_id = 5000  # engine-assigned QA ids start at 5000
        self._qas: dict[int, dict[str, Any]] = {}  # QA directory (engine-owned)
        # temp files backing loadQAfromString QAs; deleted once the QA loads
        self._temp_qa_paths: set[str] = set()
        # in-flight net.HTTPClient tasks: they count as pending work, so the
        # CLI keeps running until responses are delivered
        self._http_tasks: set[asyncio.Task[None]] = set()
        # net.TCPSocket ops run in worker threads over their own pool (the
        # debugger's sockets stay single-threaded on the main thread)
        self.qa_sockets = SyncTCPSockets()
        self.qa_udp = SyncUDPSockets()
        install_bindings(self)

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
        self._qas[qa_id] = {
            "name": name,
            "path": path,
            "code": code,
            "loaded": False,
            "type": qa_config.get("type"),
            "properties": qa_config.get("properties") or {},
            "config": qa_config,  # resolved copy (name/type/properties filled in)
        }
        # Register the QA as a device before its code runs: on the HC3 the
        # plugin device exists before onInit executes, and onInit's own api
        # calls (internalStorage, updateProperty) must find it.
        self.api.register_qa(qa_id, name, qa_config.get("type"), qa_config.get("properties") or {})
        return qa_id

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
        self.enqueue_outbound(messages.start_qa_msg(qa_id, path, config, path))
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

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._pump_task = asyncio.create_task(self._pump(), name="flua-pump")

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
        for path in list(self._temp_qa_paths):
            self._cleanup_temp_qa(path)
        for task in list(self._http_tasks):
            task.cancel()

    def is_running(self) -> bool:
        return self._running

    @property
    def exit_code(self) -> int:
        """Exit code requested by Lua via the ``exit`` message (0 = none yet)."""
        return self._exit_code

    def has_pending_work(self) -> bool:
        """True while timers, message queues, or in-flight worker tasks exist."""
        return (
            self._timers.active_count() > 0
            or bool(self._inbound)
            or not self._outbound.empty()
            or bool(self._http_tasks)
        )

    # -- pump --------------------------------------------------------------------

    async def _pump(self) -> None:
        while self._running:
            self.clock.tick(time.monotonic())
            self._timers.fire_due()
            await self._drain_inbound()
            try:
                batch = [
                    await asyncio.wait_for(self._outbound.get(), timeout=_PUMP_POLL)
                ]
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
                logger.warning(
                    "no handler for message type %r; dropped %r", msg.get("type"), msg
                )
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
        logger.debug(
            "http result id=%s %s", msg["id"], result.get("status", result.get("error"))
        )
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