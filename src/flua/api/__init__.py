"""The HC3 REST API for flua — offline simulation first, remote HC3 later.

One dispatcher, many transports: QA code reaches it through the ``_PY.api``
bridge (synchronous, no pump), and a future external HTTP server or remote
HC3 client will reuse the same handler layer. Routing is a declarative
table of (method, pattern, handler); handlers are pure functions over
``SimState`` returning ``(data, status)``. Dispatch never raises: handler
exceptions are logged and reported as status 500.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from . import routes
from .request import ApiRequest, parse_url
from .state import SimState, public

if TYPE_CHECKING:
    from ..engine import LuaEngine

logger = logging.getLogger(__name__)

Handler = Callable[[SimState, ApiRequest], tuple[Any, int]]


def _compile_routes() -> list[tuple[str, re.Pattern[str], dict[str, int], Handler]]:
    compiled: list[tuple[str, re.Pattern[str], dict[str, int], Handler]] = []
    for method, pattern, handler in routes.ROUTES:
        params: dict[str, int] = {}
        parts = [seg for seg in pattern.split("/") if seg]
        regex_parts: list[str] = []
        group_index = 1
        for seg in parts:
            if seg.startswith("{") and seg.endswith("}"):
                params[seg[1:-1]] = group_index
                group_index += 1
                regex_parts.append("([^/]+)")
            else:
                regex_parts.append(re.escape(seg))
        compiled.append((method, re.compile("^/" + "/".join(regex_parts) + "/?$"), params, handler))
    return compiled


_COMPILED = _compile_routes()


class Api:
    """Dispatch facade owned by the engine. Offline: everything is local."""

    def __init__(self, engine: LuaEngine | None = None, seed: dict[str, Any] | None = None) -> None:
        self._engine = engine  # M2+: event enqueue (device actions); None in unit tests
        self._remote = engine.hc3 if engine is not None else None  # M3: the real HC3
        self.state = SimState(seed)
        self.emitted: list[dict[str, Any]] = []  # every event enqueued (tests/introspection)

    def _emit(self, msg: dict[str, Any]) -> None:
        """Hand a pump-delivered event to the engine (and record it)."""
        self.emitted.append(msg)
        if self._engine is not None:
            self._engine.enqueue_outbound(msg)

    def register_qa(
        self,
        qa_id: int,
        name: str,
        device_type: str | None,
        properties: Any,
    ) -> None:
        self.state.register_qa(qa_id, name, device_type, properties)

    def _remote_hook(self, method: str, path: str, body: Any) -> tuple[Any, int]:
        """Forward a sim-handled call to the real HC3 (proxy mode): handlers
        use this so the controller stays in sync with the shadow device."""
        if self._remote is None:
            return None, 404
        segments, query = parse_url(path)
        remote_path = "/" + "/".join(segments)
        return self._remote.request(method, remote_path, query, body)

    def dispatch(
        self,
        method: str,
        url: str,
        body: Any = None,
        qa_id: int | None = None,
        external: bool = False,
    ) -> tuple[Any, int]:
        """Route one REST call; returns (data, status) with data=None on failures.

        ``external`` marks requests that arrived over HTTP from outside the
        emulator (viewer, proxy callbacks): the real HC3 recorded their
        events already, so handlers must not emit duplicates.
        """
        method = method.upper()
        segments, query = parse_url(url)
        if segments[:1] == ["quickApp"]:
            # /api/quickApp/* — QA source files + export, engine-backed
            # (they mutate the running QAs, not the static sim state)
            return self._quickapp(method, segments, body)
        path = "/" + "/".join(segments)
        for route_method, regex, params, handler in _COMPILED:
            if route_method != method:
                continue
            match = regex.match(path)
            if match is None:
                continue
            req = ApiRequest(
                method=method,
                segments=segments,
                query=query,
                body=body,
                path_params={name: match.group(index) for name, index in params.items()},
                emit=self._emit,
                clock=self._engine.clock if self._engine is not None else None,
                qa_id=qa_id,
                external=external,
                remote=self._remote_hook if self._remote is not None else None,
            )
            try:
                data, status = handler(self.state, req)
            except Exception:
                logger.exception("api handler failed for %s %s", method, url)
                return None, 500
            offline = self._engine is not None and self._engine.qa_is_offline(req.qa_id)
            flua_id = (
                len(segments) >= 2
                and segments[0] in ("devices", "plugins")
                and self.state.is_flua_id(segments[1])
            )
            if (
                data is None
                and status == 404
                and self._remote is not None
                and not offline
                and not flua_id
            ):
                # the sim doesn't own this entity — ask the real HC3
                return self._remote.request(method, path, query, body)
            return data, status
        logger.debug("no offline route for %s %s", method, url)
        offline = self._engine is not None and self._engine.qa_is_offline(qa_id)
        flua_id = (
            len(segments) >= 2
            and segments[0] in ("devices", "plugins")
            and self.state.is_flua_id(segments[1])
        )
        if self._remote is not None and not offline and not flua_id:
            # online mode: anything the sim doesn't own goes to the real HC3
            return self._remote.request(method, path, query, body)
        return None, 404

    def dispatch_hc3(self, method: str, url: str, body: Any = None) -> tuple[Any, int]:
        """api.hc3.*: force the REAL HC3, bypassing the hybrid dispatch —
        used by fibaro.callhc3 and test code that wants ground-truth data.
        Without a remote backend (local mode) the sim stands in."""
        if self._remote is None:
            return self.dispatch(method, url, body)
        segments, query = parse_url(url)
        path = "/" + "/".join(segments)
        return self._remote.request(method, path, query, body)

    # -- /api/quickApp/* (multi-file QAs: files + export, offline) --------------

    def _quickapp(self, method: str, segments: list[str], body: Any) -> tuple[Any, int]:
        if self._engine is None:
            return None, 404  # unit tests without an engine
        try:
            if len(segments) == 1 and method == "POST":
                # POST /quickApp — create a QuickApp device (empty main)
                device = self._engine.create_qa(body)
                return (device, 200) if device is not None else (None, 400)
            if segments[1] == "availableTypes" and method == "GET":
                return self._engine.qa_available_types(), 200
            if segments[1] == "import" and method == "POST":
                fqa = self._parse_fqa_body(body)
                if fqa is None:
                    return None, 400
                qa_id, err = self._engine.import_qa(fqa)
                if err is not None:
                    return None, 400
                device = self._engine.api.state.devices.get(qa_id)
                if device is None:
                    return None, 400
                if isinstance(body, dict) and body.get("roomId") is not None:
                    device["roomID"] = int(body["roomId"])
                return public(device), 200  # DeviceDto, like the HC3
            if segments[1] == "export" and method == "POST":
                if isinstance(body, dict) and body.get("encrypted"):
                    return None, 501  # .fqax — Fibaro-specific
                exported = self._engine.qa_export(int(segments[2]))
                return (exported, 200) if exported is not None else (None, 404)
            if segments[1] == "export" and method == "GET":
                exported = self._engine.qa_export(int(segments[2]))
                return (exported, 200) if exported is not None else (None, 404)
            device_id = int(segments[1])
            if len(segments) < 3 or segments[2] != "files":
                return None, 404
            if len(segments) == 3:
                if method == "GET":
                    files = self._engine.qa_file_list(device_id)
                    return (files, 200) if files is not None else (None, 404)
                if method == "POST":
                    # create a file (QuickAppFile body; empty by default)
                    if not isinstance(body, dict) or not body.get("name"):
                        return None, 400
                    entry = self._engine.qa_file_post(
                        device_id,
                        str(body["name"]),
                        str(body.get("type") or "lua"),
                        str(body.get("content") or ""),
                    )
                    return (entry, 200) if entry is not None else (None, 404)
                if method == "PUT":
                    # bulk update (array of QuickAppFileDetails), restart once
                    if not isinstance(body, list):
                        return None, 400
                    entries = self._engine.qa_files_put(device_id, body)
                    return (entries, 200) if entries is not None else (None, 404)
                return None, 404
            if len(segments) < 4:
                return None, 404
            name = segments[3]
            if method == "GET":
                entry = self._engine.qa_file_get(device_id, name)
                return (entry, 200) if entry is not None else (None, 404)
            if method == "PUT":
                existing = self._engine.qa_file_get(device_id, name)
                if existing is not None and existing["isMain"]:
                    return None, 403  # offline: main lives on the user's disk
                content = body.get("content") if isinstance(body, dict) else body
                if not isinstance(content, str):
                    return None, 400
                entry = self._engine.qa_file_put(device_id, name, content)
                return (entry, 200) if entry is not None else (None, 404)
            if method == "DELETE":
                return (None, 200) if self._engine.qa_file_delete(device_id, name) else (None, 404)
            return None, 404
        except (ValueError, IndexError):
            return None, 404

    @staticmethod
    def _parse_fqa_body(body: Any) -> dict[str, Any] | None:
        """Accept the documented base64 body ({"file": "<base64>"}) or a
        direct .fqa table (flua convenience)."""
        if not isinstance(body, dict):
            return None
        if "file" in body:
            raw = str(body["file"]).strip()
            try:
                raw += "=" * (-len(raw) % 4)  # tolerate missing padding
                fqa = json.loads(base64.b64decode(raw).decode("utf-8"))
            except Exception:
                return None
        else:
            fqa = body
        if not isinstance(fqa, dict) or not isinstance(fqa.get("files"), list):
            return None
        return fqa
