"""Request plumbing for the HC3 REST API dispatcher.

The dispatcher is transport-agnostic: it maps (method, path, query, body)
to (data, status) and is reached from the Lua bridge today; a remote HC3
client or an external HTTP server will reuse the same handler layer later.
This module stays free of asyncio and lupa on purpose.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote


@dataclass
class ApiRequest:
    """One parsed REST request.

    ``segments`` and ``path_params`` are percent-decoded; ``query`` holds
    the query string (last value wins, like most HTTP stacks).
    """

    method: str
    segments: list[str]
    query: dict[str, str]
    body: Any
    path_params: dict[str, str] = field(default_factory=dict)
    qa_id: int | None = None
    clock: Any = None  # the engine's virtual clock (refreshStates timestamps)
    # Filled by Api.dispatch: handlers call this to hand an event to the
    # engine's outbound queue (device actions, custom events). None when a
    # handler is invoked outside dispatch.
    emit: Callable[[dict[str, Any]], None] | None = None


def parse_url(url: str) -> tuple[list[str], dict[str, str]]:
    """Split ``/devices/45?type=x`` into decoded segments and a query dict."""
    path, _, query_string = url.partition("?")
    segments = [unquote(seg) for seg in path.split("/") if seg]
    query: dict[str, str] = {}
    for key, values in parse_qs(query_string, keep_blank_values=True).items():
        query[key] = values[-1]
    return segments, query
