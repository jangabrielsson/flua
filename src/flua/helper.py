"""The HC3 helper bridge — flua's way into the HC3's LOCAL API context.

Some HC3 endpoints (single-key variables, variable writes, and other
local-only surface) refuse external callers — the emulator cannot call
them directly. The solution is a small invisible QA deployed on the
controller (``src/flua/lua/FluaHelper_main.lua``, uploaded by
``flua --tool installHelper``): it opens a WebSocket OUT to the emulator
and executes ``{id, method, path, data}`` requests through its own
``api.*`` — which runs in the HC3's local context — sending
``{id, ok, data, status}`` back.

This module is the emulator side of that connection: an engine-owned
WebSocket server (bound on all interfaces — the controller must reach the
laptop) that accepts the helper's connection and turns RPC calls into
pending futures. Calls are made from the api-dispatch worker threads, so
the pump never blocks on the controller.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import re
import socket
from pathlib import Path
from typing import Any

from .server import _WS_GUID, _read_http_request, _read_ws_frame, _ws_frame

logger = logging.getLogger(__name__)

DEFAULT_HELPER_PORT = 8099
_HELPER_TIMEOUT = 15.0  # seconds an RPC may take before the caller gets (nil, 0)
_HELPER_WAKE_WAIT = 8.0  # seconds to wait for the helper's dial-back after the connect action

_HELPER_SOURCE = Path(__file__).resolve().parent / "lua" / "FluaHelper_main.lua"


def helper_identity() -> tuple[str, str]:
    """(uuid, version) from the bundled helper source — the identity the
    deployed QA reports through its properties (the version bumps only on
    protocol changes)."""
    source = _HELPER_SOURCE.read_text(encoding="utf-8")
    uuid_match = re.search(r'HELPER_UUID = "([^"]+)"', source)
    version_match = re.search(r'HELPER_VERSION = "([^"]+)"', source)
    if uuid_match is None or version_match is None:
        raise ValueError("FluaHelper_main.lua must declare HELPER_UUID and HELPER_VERSION")
    return uuid_match.group(1), version_match.group(1)


class Hc3Helper:
    """Accept one FluaHelper connection and serve RPCs over it."""

    def __init__(self, port: int = DEFAULT_HELPER_PORT) -> None:
        self.port = port
        self._server: asyncio.Server | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[int, asyncio.Future[tuple[Any, int]]] = {}
        self._next_id = 1
        self.connected = False
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        try:
            # 0.0.0.0 on purpose: the helper QA on the controller connects
            # to the laptop over the LAN (every other flua server binds
            # 127.0.0.1).
            self._server = await asyncio.start_server(self._accept, host="0.0.0.0", port=self.port)
        except OSError as exc:
            logger.warning(
                "helper server: cannot bind 0.0.0.0:%d (%s) — helper disabled",
                self.port,
                exc,
            )
            return
        logger.info("flua helper server listening on 0.0.0.0:%d", self.port)

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._writer is not None:
            with contextlib.suppress(Exception):
                self._writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        self._fail_pending()

    def _fail_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result((None, 0))
        self._pending.clear()
        self.connected = False

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await _read_http_request(reader)
            if request is None:
                return
            _, _, headers, _ = request
            key = headers.get("sec-websocket-key")
            if not key:
                return
            accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
            writer.write(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode("latin-1")
            )
            await writer.drain()
            # a new helper connection replaces the old one (single-helper
            # model, like plua) — anything in flight on the old one is lost
            self._fail_pending()
            self._writer = writer
            self.connected = True
            logger.info("helper QA connected")
            while True:
                frame = await _read_ws_frame(reader)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:  # ping -> pong
                    writer.write(_ws_frame(0xA, payload))
                    await writer.drain()
                    continue
                if opcode in (0x1, 0x2):
                    self._on_message(payload.decode("utf-8", errors="replace"))
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
            pass
        finally:
            if self._writer is writer:
                self.connected = False
                self._writer = None
            self._fail_pending()
            with contextlib.suppress(Exception):
                writer.close()

    def _on_message(self, text: str) -> None:
        try:
            reply = json.loads(text)
        except ValueError:
            logger.warning("helper: not JSON: %.200s", text)
            return
        if not isinstance(reply, dict):
            return
        fut = self._pending.pop(reply.get("id"), None)
        if fut is None or fut.done():
            return
        fut.set_result(reply)

    async def call(
        self, method: str, path: str, data: Any, timeout: float = _HELPER_TIMEOUT
    ) -> tuple[Any, int]:
        """Send one RPC to the helper and await its reply. Runs on the
        engine's event loop (via run_coroutine_threadsafe from the api
        worker threads); returns (data, status) with (nil, 0) when the
        helper is not connected or never answers."""
        writer = self._writer
        if writer is None:
            return None, 0
        rid = self._next_id
        self._next_id += 1
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            payload = json.dumps(
                {"id": rid, "method": method, "path": path, "data": data}
            ).encode("utf-8")
            writer.write(_ws_frame(0x1, payload))
            await writer.drain()
            reply = await asyncio.wait_for(fut, timeout)
            return reply.get("data"), reply.get("status", 0)
        except (TimeoutError, ConnectionError, OSError):
            return None, 0
        finally:
            self._pending.pop(rid, None)

    async def call_fibaro(
        self, name: str, args: list[Any], timeout: float = _HELPER_TIMEOUT
    ) -> tuple[Any, bool]:
        """Run fibaro.<name>(...) inside the helper QA and return its values.
        Returns (values, True) with values the list of the function's return
        values, or (error, False) when the helper is not connected, never
        answers, or the function raised (error is then the message)."""
        writer = self._writer
        if writer is None:
            return None, False
        rid = self._next_id
        self._next_id += 1
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            payload = json.dumps(
                {"id": rid, "kind": "fibaro", "name": name, "args": args}
            ).encode("utf-8")
            writer.write(_ws_frame(0x1, payload))
            await writer.drain()
            reply = await asyncio.wait_for(fut, timeout)
            values = reply.get("values")
            if reply.get("ok") and isinstance(values, list):
                return values, True
            return (values[0] if isinstance(values, list) and values else None), False
        except (TimeoutError, ConnectionError, OSError):
            return None, False
        finally:
            self._pending.pop(rid, None)

    # -- tool support ----------------------------------------------------------

    @staticmethod
    def lan_ip(remote_host: str) -> str:
        """The local address the controller sees this machine at: route a
        UDP socket toward the HC3 and read the chosen source address."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((remote_host, 80))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            sock.close()
