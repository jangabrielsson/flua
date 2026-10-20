"""Blocking HTTP calls for net.HTTPClient (run in a thread executor).

flua's Lua side is cooperative and the pump must never block, so requests
are executed with ``urllib`` (stdlib — lupa stays the only dependency) in a
worker thread; the engine delivers the result back through the message pump
as an ``httpResult`` message. This module is deliberately free of asyncio:
it is one synchronous function, safe to run in any thread.
"""

from __future__ import annotations

import contextlib
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any

SHUT_RDWR = socket.SHUT_RDWR

USER_AGENT = "flua/0.1"


def http_call(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    data: str | bytes | None = None,
    timeout: float = 30.0,
    check_certificate: bool = True,
) -> tuple[int, str, dict[str, str]]:
    """One blocking HTTP exchange -> (status, body, headers).

    Any HTTP response — including 4xx/5xx — is returned with its status;
    only transport-level failures (DNS, refused, timeout) raise. This
    mirrors the HC3: ``success`` receives completed exchanges and can check
    ``response.status``; ``error`` fires for failures to reach the server.
    ``check_certificate=False`` skips HTTPS certificate verification (the
    HC3's checkCertificate option; Python verifies by default, like the
    HC3's default true).
    """
    status, response_headers, response = open_http(
        method, url, headers, data, timeout, check_certificate
    )
    try:
        return status, response.read().decode("utf-8", errors="replace"), response_headers
    finally:
        with contextlib.suppress(Exception):
            response.close()


def open_http(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    data: str | bytes | None = None,
    timeout: float = 30.0,
    check_certificate: bool = True,
) -> tuple[int, dict[str, str], Any]:
    """Open an HTTP exchange: (status, headers, response). The caller owns
    and must close the response; transport failures raise. HTTP errors
    (4xx/5xx) return their response as the file-like object, like http_call."""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", USER_AGENT)
    if isinstance(data, bytes):
        payload = data
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    else:
        payload = None
    context = None if check_certificate else ssl._create_unverified_context()
    request = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())
    try:
        response = urllib.request.urlopen(request, timeout=timeout, context=context)
        return response.status, dict(response.headers.items()), response
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc


def abort_http_response(response: Any) -> None:
    """Force-close an HTTP response's socket.

    urllib's response.close() DRAINS chunked responses (to keep the
    connection reusable), which blocks on a live SSE stream until the next
    event arrives — the exit() linger seen against the Hue bridge. Closing
    the socket directly unblocks the reader immediately."""
    try:
        fp = getattr(response, "fp", None)
        raw = getattr(fp, "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None:
            # shutdown interrupts a recv() blocked in another thread; a bare
            # close() does not (verified: the parked chunked readline ignores
            # it until data arrives — the Hue bridge linger)
            with contextlib.suppress(OSError):
                sock.shutdown(SHUT_RDWR)
            sock.close()
    except Exception:
        pass
    with contextlib.suppress(Exception):
        response.close()


def read_sse_block(response: Any) -> str | None:
    """One raw SSE event block from a text/event-stream response: the lines
    through the terminating blank line (the block the HC3 hands its success
    callback). None on EOF (the stream ended — silent on the HC3). Read
    errors and timeouts raise."""
    block: list[str] = []
    while True:
        line = response.readline()
        if line == b"":
            return None
        block.append(line.decode("utf-8", errors="replace"))
        if line in (b"\n", b"\r\n"):
            return "".join(block)
