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

    def register_qa(self, qa_id: int, name: str, device_type: str | None, properties: Any) -> None:
        self.state.register_qa(qa_id, name, device_type, properties)

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