"""The HC3 REST API for flua — offline simulation first, remote HC3 later.

One dispatcher, many transports: QA code reaches it through the ``_PY.api``
bridge (synchronous, no pump), and a future external HTTP server or remote
HC3 client will reuse the same handler layer. Routing is a declarative
table of (method, pattern, handler); handlers are pure functions over
``SimState`` returning ``(data, status)``. Dispatch never raises: handler
exceptions are logged and reported as status 500.
"""

from __future__ import annotations

import logging
import re
import base64
import json
from typing import TYPE_CHECKING, Any, Callable

from . import routes
from .request import ApiRequest, parse_url
from .state import SimState

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

    def __init__(self, engine: "LuaEngine | None" = None, seed: dict[str, Any] | None = None) -> None:
        self._engine = engine  # M2+: event enqueue (device actions); None in unit tests
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
        variables: dict[str, Any] | None = None,
    ) -> None:
        self.state.register_qa(qa_id, name, device_type, properties, variables)

    def dispatch(
        self,
        method: str,
        url: str,
        body: Any = None,
        qa_id: int | None = None,
    ) -> tuple[Any, int]:
        """Route one REST call; returns (data, status) with data=None on failures."""
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
                qa_id=qa_id,
            )
            try:
                data, status = handler(self.state, req)
            except Exception:
                logger.exception("api handler failed for %s %s", method, url)
                return None, 500
            return data, status
        logger.debug("no offline route for %s %s", method, url)
        return None, 404

    # -- /api/quickApp/* (multi-file QAs: files + export, offline) --------------

    def _quickapp(self, method: str, segments: list[str], body: Any) -> tuple[Any, int]:
        if self._engine is None:
            return None, 404  # unit tests without an engine
        try:
            if segments[1] == "import" and method == "POST":
                fqa = self._parse_fqa_body(body)
                if fqa is None:
                    return None, 400
                qa_id, err = self._engine.import_qa(fqa)
                if err is not None:
                    return None, 400
                return qa_id, 201
            if segments[1] == "export" and method == "POST":
                # encrypted .fqax — Fibaro-specific, not supported offline
                return None, 501
            if segments[1] == "export" and method == "GET":
                exported = self._engine.qa_export(int(segments[2]))
                return (exported, 200) if exported is not None else (None, 404)
            device_id = int(segments[1])
            if len(segments) < 3 or segments[2] != "files":
                return None, 404
            if len(segments) == 3 and method == "GET":
                files = self._engine.qa_file_list(device_id)
                return (files, 200) if files is not None else (None, 404)
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
                return (None, 204) if self._engine.qa_file_delete(device_id, name) else (None, 404)
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