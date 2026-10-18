"""Session tools: a running flua engine an agent can probe across calls.

One LuaEngine per session, on its own asyncio loop in a daemon thread (the
engine assumes it owns its loop — mirrors how every test drives engines).
The MCP transport stays stateless: the session id is an explicit tool
argument, never connection state. Idle sessions are reaped on a TTL so a
forgetful agent cannot leak engines.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import uuid
from typing import Any

from ..engine import LuaEngine

DEFAULT_TTL = 600.0  # idle seconds before a session is reaped
_SHUTDOWN_TIMEOUT = 5.0


class _Session:
    def __init__(
        self,
        session_id: str,
        engine: LuaEngine,
        loop: asyncio.AbstractEventLoop,
        thread: threading.Thread,
        ttl: float,
    ) -> None:
        self.session_id = session_id
        self.engine = engine
        self.loop = loop
        self.thread = thread
        self.ttl = ttl
        self.qa_ids: list[int] = []
        self.last_used = time.monotonic()
        self.debug_last = 0  # /debugMessages cursor for probe deltas
        self.sys_last = 0  # /flua/systemLog cursor for probe deltas
        self.refresh_last = 0  # /refreshStates cursor for probe deltas


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------------

    def start(
        self,
        files: list[str],
        mode: str | None,
        instant: bool,
        speed: float | None,
        start: float | None,
        ttl: float,
    ) -> dict[str, Any]:
        """Boot a session: one engine, N QAs, on a dedicated loop/thread.
        Blocks until the QAs are loaded. Returns {sessionId, qaIds}."""
        self.reap()
        session_id = uuid.uuid4().hex[:12]
        loop = asyncio.new_event_loop()
        try:
            engine = LuaEngine(
                api_mode="local" if mode is None else mode,
                speed=float("inf") if instant else (speed if speed is not None else 1.0),
                start=start,
                log_stream=sys.stderr,  # stdout stays pure JSON-RPC on the stdio transport
            )
        except ValueError as exc:
            loop.close()
            raise exc
        session = _Session(session_id, engine, loop, threading.Thread(), ttl)
        ready: dict[str, Any] = {}

        def thread_main() -> None:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._bootstrap(session, files, ready))
            loop.run_forever()

        session.thread = threading.Thread(
            target=thread_main, name=f"flua-mcp-{session_id}", daemon=True
        )
        with self._lock:
            self._sessions[session_id] = session
        session.thread.start()
        deadline = time.monotonic() + 30.0
        while "ok" not in ready and time.monotonic() < deadline:
            time.sleep(0.01)
        if "ok" not in ready:
            self._teardown(session)
            with self._lock:
                self._sessions.pop(session_id, None)
            raise RuntimeError(ready.get("error") or "session start timed out")
        session.qa_ids = ready["qa_ids"]
        return {"sessionId": session_id, "qaIds": ready["qa_ids"]}

    async def _bootstrap(self, session: _Session, files: list[str], ready: dict[str, Any]) -> None:
        try:
            await session.engine.start()
            qa_ids: list[int] = []
            for path in files:
                # load_qa_file = CLI parity: the file's --%% directives reach
                # the engine (names, properties, per-QA clock settings)
                qa_id, error = session.engine.load_qa_file(path)
                if error is not None:
                    ready["error"] = f"{path}: {error}"
                    return
                assert qa_id is not None
                qa_ids.append(qa_id)
            ready.update(ok=True, qa_ids=qa_ids)
        except Exception as exc:
            ready["error"] = str(exc)

    def stop(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        self._teardown(session)
        return True

    def _teardown(self, session: _Session) -> None:
        loop = session.loop
        if loop.is_closed():
            return
        future = asyncio.run_coroutine_threadsafe(session.engine.stop(), loop)
        try:
            future.result(timeout=_SHUTDOWN_TIMEOUT)
        except Exception:
            pass  # teardown must never raise
        loop.call_soon_threadsafe(loop.stop)
        session.thread.join(timeout=_SHUTDOWN_TIMEOUT)

    def shutdown(self) -> None:
        """Stop every session (server exit)."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            self._teardown(session)

    def reap(self) -> None:
        """Stop sessions idle past their TTL (called lazily on each op)."""
        now = time.monotonic()
        with self._lock:
            expired = [
                s for s in self._sessions.values() if now - s.last_used > s.ttl
            ]
            for session in expired:
                self._sessions.pop(session.session_id, None)
        for session in expired:
            self._teardown(session)

    def get(self, session_id: str) -> _Session:
        """Look the session up, touching it (a probe IS usage): an idle-
        past-TTL session that is being asked about is revived, never reaped
        by its own request. Reaping stays lazy for everything else."""
        with self._lock:
            session = self._sessions.get(session_id)
        if session is not None:
            session.last_used = time.monotonic()
            return session
        self.reap()
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"unknown session: {session_id}")
        session.last_used = time.monotonic()
        return session

    def list(self) -> list[dict[str, Any]]:
        self.reap()
        now = time.monotonic()
        with self._lock:
            sessions = list(self._sessions.values())
        return [
            {
                "sessionId": s.session_id,
                "qaIds": s.qa_ids,
                "ageSeconds": round(now - s.last_used, 1),
            }
            for s in sessions
        ]

    # -- probing --------------------------------------------------------------

    def probe(self, session: _Session) -> dict[str, Any]:
        devices, status = session.engine.api.dispatch("GET", "/devices")
        qas = [
            {
                "id": qa_id,
                "name": session.engine.qa_info(qa_id).get("name"),
                "loaded": session.engine.qa_info(qa_id).get("loaded"),
                "type": session.engine.qa_info(qa_id).get("type"),
            }
            for qa_id in session.engine.qa_ids()
        ]
        debug, _ = session.engine.api.dispatch(
            "GET", f"/debugMessages?last={session.debug_last}"
        )
        session.debug_last = (
            debug.get("nextLast") if isinstance(debug, dict) else session.debug_last
        )
        system, _ = session.engine.api.dispatch("GET", f"/flua/systemLog?last={session.sys_last}")
        session.sys_last = system.get("nextLast") if isinstance(system, dict) else session.sys_last
        refresh, _ = session.engine.api.dispatch(
            "GET", f"/refreshStates?last={session.refresh_last}"
        )
        if isinstance(refresh, dict):
            session.refresh_last = refresh.get("last", session.refresh_last)
        return {
            "devices": devices if status == 200 else None,
            "qas": qas,
            "debugMessages": debug.get("messages") if isinstance(debug, dict) else [],
            "systemEvents": system.get("entries") if isinstance(system, dict) else [],
            "refreshStates": refresh if isinstance(refresh, dict) else None,
        }

    def action(self, session: _Session, qa_id: int, action: str, args: list[Any]) -> dict[str, Any]:
        data, status = session.engine.api.dispatch(
            "POST", f"/devices/{qa_id}/action/{action}", {"args": args}
        )
        return {"status": status}
