"""Blocking HTTP calls for net.HTTPClient (run in a thread executor).

flua's Lua side is cooperative and the pump must never block, so requests
are executed with ``urllib`` (stdlib — lupa stays the only dependency) in a
worker thread; the engine delivers the result back through the message pump
as an ``httpResult`` message. This module is deliberately free of asyncio:
it is one synchronous function, safe to run in any thread.
"""

from __future__ import annotations

import urllib.error
import urllib.request

USER_AGENT = "flua/0.1"


def http_call(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    data: str | None = None,
    timeout: float = 30.0,
) -> tuple[int, str, dict[str, str]]:
    """One blocking HTTP exchange -> (status, body, headers).

    Any HTTP response — including 4xx/5xx — is returned with its status;
    only transport-level failures (DNS, refused, timeout) raise. This
    mirrors the HC3: ``success`` receives completed exchanges and can check
    ``response.status``; ``error`` fires for failures to reach the server.
    """
    headers = dict(headers or {})
    headers.setdefault("User-Agent", USER_AGENT)
    payload = data.encode("utf-8") if isinstance(data, str) else None
    request = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read()
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
        response_headers = dict(exc.headers.items()) if exc.headers else {}
    return status, body.decode("utf-8", errors="replace"), response_headers