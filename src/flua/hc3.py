"""Remote HC3 REST client (M3): the online half of the api dispatcher.

Blocking urllib calls — the api.* surface is synchronous (like on the HC3),
so a remote call blocks the calling QA's thread for the HTTP round trip.
LAN-local, typically a few milliseconds; the pump is frozen for the
duration (same documented exception as the debugger's sockets).

Safety: the HC3 locks itself after 4 failed credential attempts, so any
401/403 response aborts flua immediately through the on_auth_error hook —
it is never retried.
"""

from __future__ import annotations

import base64
import json
import logging
import binascii
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Hc3Remote:
    def __init__(
        self,
        base_url: str,
        user: str | None = None,
        password: str | None = None,
        pin: str | None = None,
        on_auth_error: Callable[[int, str], None] | None = None,
        timeout: float = 10.0,
    ) -> None:
        base_url = base_url.rstrip("/")
        if base_url.endswith("/api"):
            base_url = base_url[: -len("/api")]
        self._base = base_url
        self._user = user
        self._password = password
        self._pin = pin
        self._on_auth_error = on_auth_error
        self._timeout = timeout

    def _auth_header(self) -> str | None:
        if not self._user:
            return None
        token = base64.b64encode(f"{self._user}:{self._password or ''}".encode()).decode()
        return f"Basic {token}"

    def request(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        body: Any = None,
        timeout: float | None = None,
    ) -> tuple[Any, int]:
        """One REST call -> (data, status). A 401/403 invokes the auth guard
        and aborts flua — never retried (the HC3 locks after 4 attempts)."""
        url = self._base + "/api" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Accept": "application/json"}
        auth = self._auth_header()
        if auth:
            headers["Authorization"] = auth
        payload = None
        if body is not None:
            if isinstance(body, str):
                # raw string bodies go verbatim — plua's api.post data path
                # (httpx content=); no Content-Type, like httpx.
                payload = body.encode("utf-8")
            elif (
                method.upper() == "POST"
                and path.startswith("/quickApp")
                and isinstance(body, dict)
                and "file" in body
            ):
                # flua's offline convention {file = base64, roomId}: the real
                # HC3 takes the .fqa as the raw JSON body (verified against
                # plua's uploadFQA: api.hc3.post("/quickApp/", fqaString)).
                # roomId rides the query string.
                try:
                    raw = str(body["file"])
                    payload = base64.b64decode(raw + "=" * (-len(raw) % 4))
                except (ValueError, binascii.Error):
                    return None, 400  # malformed base64: the HC3 is never called
                if body.get("roomId") is not None:
                    query = dict(query or {})
                    query.setdefault("roomId", str(int(body["roomId"])))
                    url = self._base + "/api" + path + "?" + urllib.parse.urlencode(query)
            else:
                payload = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())
        return self._exchange(request, method, path, url, timeout)

    def _exchange(
        self,
        request: urllib.request.Request,
        method: str,
        path: str,
        url: str,
        timeout: float | None = None,
    ) -> tuple[Any, int]:
        try:
            with urllib.request.urlopen(request, timeout=timeout or self._timeout) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        except Exception as exc:
            logger.debug("hc3 request failed for %s %s: %s", method, path, exc)
            return None, 0  # transport failure: no HTTP status
        if status in (401, 403):
            if self._on_auth_error is not None:
                self._on_auth_error(status, url)
            return None, status
        if not raw:
            return None, status
        try:
            return json.loads(raw.decode("utf-8")), status
        except ValueError:
            return raw.decode("utf-8", errors="replace"), status