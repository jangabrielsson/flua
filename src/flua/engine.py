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
import logging
import sys
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import lupa

from . import messages
from .bindings import install_bindings
from .clock import VirtualClock
from .sync_socket import SyncTCPSockets
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
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            messages.SET_TIMEOUT: self._handle_set_timeout,
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
        install_bindings(self)

    # -- bridge surface (used by bindings.py) ---------------------------------

    def post(self, msg: dict[str, Any]) -> None:
        """Append a Lua -> Python message. Never blocks, never calls Lua."""
        self._inbound.append(msg)

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
        }
        lua = self._lua
        cfg = lua.table_from(qa_config, recursive=True)
        arg = lua.table()
        arg[0] = arg0
        flua = lua.globals()["_FLUA"]
        if path is not None:
            flua["startQaFile"](qa_id, path, cfg, arg)
        else:
            flua["startQaCode"](qa_id, code, cfg, arg)
        return qa_id

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

    def is_running(self) -> bool:
        return self._running

    @property
    def exit_code(self) -> int:
        """Exit code requested by Lua via the ``exit`` message (0 = none yet)."""
        return self._exit_code

    def has_pending_work(self) -> bool:
        """True while timers are active or either message queue is non-empty."""
        return (
            self._timers.active_count() > 0
            or bool(self._inbound)
            or not self._outbound.empty()
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
        self._timers.set_timeout(int(msg["id"]), int(msg["delay"]))

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
        self._exit_code = int(msg.get("code", 0))
        self._running = False

    def _handle_qa_loaded(self, msg: dict[str, Any]) -> None:
        qa_id = int(msg["id"])
        info = self._qas.get(qa_id)
        if info is not None:
            info["loaded"] = True
            logger.debug("QA %d (%s) loaded", qa_id, info["name"])

    # -- timer bridge ---------------------------------------------------------------

    def _on_timer_fired(self, timer_id: int) -> None:
        self.enqueue_outbound(messages.timer_expired(timer_id))

    def note_debugger_pause(self) -> None:
        """Freeze virtual time while the debugger waits (mobdebug yield hook)."""
        self.clock.note_pause()
