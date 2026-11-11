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
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from . import routes
from .request import ApiRequest, parse_url
from .state import SimState, public

if TYPE_CHECKING:
    from ..engine import LuaEngine

logger = logging.getLogger(__name__)

Handler = Callable[[SimState, ApiRequest], tuple[Any, int]]

# The HC3 refuses external REST callers for the single-key QA variable
# endpoints and for every variable write (list GET is the only one that
# works from outside) — those routes go through the FluaHelper bridge in
# online/proxy mode instead of the plain REST fallback.
_VARIABLES_KEY_RE = re.compile(r"^/plugins/\d+/variables/([^/]+)$")
_VARIABLES_LIST_RE = re.compile(r"^/plugins/\d+/variables$")


def _variables_via_helper(method: str, path: str) -> bool:
    """True when this variables call must reach the controller through the
    helper QA (the REST transport would get a 500)."""
    if _VARIABLES_KEY_RE.match(path):
        return True
    return _VARIABLES_LIST_RE.match(path) is not None and method != "GET"


def compile_pattern(pattern: str) -> tuple[re.Pattern[str], dict[str, int]]:
    """One route pattern -> (regex, params): ``{name}`` segments become
    capture groups (match any non-slash segment), everything else is
    literal. Shared by the built-in route table and user-registered
    endpoints (``api.registerEndpoint``)."""
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
    return re.compile("^/" + "/".join(regex_parts) + "/?$"), params


def _compile_routes() -> list[tuple[str, re.Pattern[str], dict[str, int], Handler]]:
    compiled: list[tuple[str, re.Pattern[str], dict[str, int], Handler]] = []
    for method, pattern, handler in routes.ROUTES:
        regex, params = compile_pattern(pattern)
        compiled.append((method, regex, params, handler))
    return compiled


_COMPILED = _compile_routes()

# Shape-only stubs: HC3-shaped 200 responses with empty/zeroed data — the
# docs/rest-endpoints.md "Stub" column, now machine-readable (that table
# points here; update both together). They look plausible to a QA that
# expects real controller state, so the runtime warns on first use
# (--%%warn:stubApi=false silences).
SHAPE_ONLY_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/iosDevices"),
        ("GET", "/alarms/v1/devices"),
        ("GET", "/notificationCenter"),
        ("GET", "/energy/devices"),
        ("GET", "/users"),
        ("GET", "/panels/climate"),
        ("GET", "/panels/climate/{id}"),
        ("GET", "/panels/notifications"),
        ("GET", "/panels/family"),
        ("GET", "/panels/sprinklers"),
        ("GET", "/panels/humidity"),
        ("GET", "/panels/favoriteColors"),
        ("GET", "/panels/favoriteColors/v2"),
    }
)
# flua-only routes with no HC3 counterpart (extensions beyond the /flua/
# channel, which is classified by path).
_EXTENSION_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/devices"),  # flua extension: base device from the type skeleton
        ("PUT", "/weather"),  # flua extension: the HC3's weather is provider-owned
    }
)
_SHAPE_ONLY_COMPILED = [
    (method, compile_pattern(pattern)[0]) for method, pattern in SHAPE_ONLY_ROUTES
]

# /quickApp/* is engine-backed (Api._dispatch routes it before the route
# table) — the audit classifier and the user-route pre-check must still
# count these paths as built-in/simulated. Mirrors Api._quickapp.
_QUICKAPP_ROUTES = (
    ("POST", "/quickApp"),
    ("GET", "/quickApp/availableTypes"),
    ("GET", "/quickApp/export/{deviceId}"),
    ("POST", "/quickApp/export/{deviceId}"),
    ("POST", "/quickApp/import"),
    ("GET", "/quickApp/{deviceId}/files"),
    ("POST", "/quickApp/{deviceId}/files"),
    ("PUT", "/quickApp/{deviceId}/files"),
    ("DELETE", "/quickApp/{deviceId}/files/{fileName}"),
    ("GET", "/quickApp/{deviceId}/files/{fileName}"),
    ("PUT", "/quickApp/{deviceId}/files/{fileName}"),
)
_QUICKAPP_COMPILED = [
    (method, compile_pattern(pattern)[0]) for method, pattern in _QUICKAPP_ROUTES
]


def qa_context_status(method: str, path: str, status: int) -> int:
    """The HC3's QA-runtime api.* layer: where it differs from the external
    REST, QAs observe the local layer. Live-verified 5.221 by the parity
    probe QA — unknown routes answer 501 (not 404), and GET /plugins/{id}
    answers 501 even for the QA's own id (the variables routes stay
    readable, which is why QAs hold their state there)."""
    if status == 404 and not route_match(method, path):
        return 501
    if method.upper() == "GET" and re.fullmatch(r"/plugins/\d+", path.split("?", 1)[0]):
        return 501
    return status


def route_match(method: str, path: str) -> bool:
    """Whether the sim implements (method, path) — the coverage audit's
    classifier (``flua audit``) and the registered-endpoint pre-check.
    ``path`` may use ``{param}`` placeholders (a placeholder matches any
    non-slash segment); query strings are not part of the route."""
    path = path.split("?", 1)[0]
    if "{" in path:
        path = re.sub(r"\{[^/{}]*\}", "x", path)
    for route_method, pattern, _params, _handler in _COMPILED:
        if route_method == method.upper() and pattern.match(path):
            return True
    for route_method, pattern in _QUICKAPP_COMPILED:
        if route_method == method.upper() and pattern.match(path):
            return True
    return False


def route_classification(method: str, path: str) -> str | None:
    """What the sim serves for (method, path): ``"state"`` (real simulated
    data), ``"stub"`` (HC3-shaped but empty/zeroed), ``"extension"``
    (flua-only surface, no HC3 counterpart), or None (not implemented —
    forwarded online). Drives --capabilities-json's rest table and the
    default-on shape-only-stub warning (--%%warn:stubApi=false silences)."""
    method = method.upper()
    path = path.split("?", 1)[0]
    normalized = re.sub(r"\{[^/{}]*\}", "x", path) if "{" in path else path
    if path == "/proxy" or path.startswith("/flua/"):
        return "extension"
    for stub_method, regex in _SHAPE_ONLY_COMPILED:
        if stub_method == method and regex.match(normalized):
            return "stub"
    if (method, path) in _EXTENSION_ROUTES:
        return "extension"
    if route_match(method, path):
        return "state"
    return None


def _trace_body(body: Any) -> str:
    """A JSON-safe, truncated rendering of an api request body for the
    --trace api/ui events (bodies may carry secrets or be huge)."""
    try:
        text = json.dumps(body, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(body)
    return text if len(text) <= 1000 else text[:1000] + "..."


def _fqa_from_multipart(body: str | bytes) -> dict[str, Any] | None:
    """The multipart/form-data wire format the HC3 web UI uses for
    POST /quickApp/import: the ``file`` part carries the .fqa JSON. The
    dispatcher only sees the body (no headers), so the boundary is
    recovered from the first line (``--boundary\r\n``). Parses just enough
    — the parts and the file content."""
    raw = body.encode("utf-8", errors="replace") if isinstance(body, str) else body
    first_line = raw.split(b"\r\n", 1)[0]
    if not first_line.startswith(b"--"):
        return None
    boundary = first_line[2:].rstrip()
    if not boundary:
        return None
    for part in raw.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        head, _, content = part.partition(b"\r\n\r\n")
        name = re.search(rb'name="([^"]+)"', head)
        if name is None or name.group(1).decode() != "file":
            continue
        try:
            fqa = json.loads(content.decode("utf-8"))
        except ValueError:
            return None
        if not isinstance(fqa, dict) or not isinstance(fqa.get("files"), list):
            return None
        return fqa
    return None


class Api:
    """Dispatch facade owned by the engine. Offline: everything is local."""

    def __init__(self, engine: LuaEngine | None = None, seed: dict[str, Any] | None = None) -> None:
        self._engine = engine  # M2+: event enqueue (device actions); None in unit tests
        self._remote = engine.hc3 if engine is not None else None  # M3: the real HC3
        # online mode: the FluaHelper bridge for the variables endpoints the
        # HC3 refuses to external REST callers (engine-wired; None offline)
        self._helper_bridge = (
            engine._helper_bridge if engine is not None and engine.hc3 is not None else None
        )
        self.state = SimState(seed)
        self.emitted: list[dict[str, Any]] = []  # every event enqueued (tests/introspection)
        # SimState access is serialized: remote-mode QA api calls run in
        # worker threads (async dispatch), the pump mutates state in
        # between. Contention is rare (sim-side work is microseconds); the
        # lock may be held across a remote HTTP call inside a handler's
        # forwarding path — the pump keeps delivering timers regardless.
        self._dispatch_lock = threading.RLock()
        # run-lifetime cache for _remote_cached GETs (base-struct merges)
        self._remote_cache: dict[str, tuple[Any, int]] = {}
        # paths whose lazy fetch already failed this run (one warning each)
        self._remote_failed: set[str] = set()

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
        proxy: bool = False,
    ) -> dict[str, Any] | None:
        """Register a running QA as a device; returns the recorded
        DeviceCreatedEvent (None for proxy QAs — the real HC3 emits those)."""
        now = self._engine.clock.time if self._engine is not None else time.time()
        return self.state.register_qa(qa_id, name, device_type, properties, proxy=proxy, now=now)

    def _remote_hook(self, method: str, path: str, body: Any) -> tuple[Any, int]:
        """Forward a sim-handled call to the real HC3 (proxy mode): handlers
        use this so the controller stays in sync with the shadow device."""
        if self._remote is None:
            return None, 404
        segments, query = parse_url(path)
        remote_path = "/" + "/".join(segments)
        return self._remote.request(method, remote_path, query, body)

    def _remote_cached(self, path: str) -> tuple[Any, int] | None:
        """One lazy GET against the real HC3, cached for the run: base
        structs (device 1, /home, /settings/info, /settings/location) merge
        controller values into the sim's virtual-clock views. None offline
        or when the controller can't answer."""
        if self._remote is None:
            return None
        if path not in self._remote_cache:
            segments, query = parse_url(path)
            remote_path = "/" + "/".join(segments)
            data, status = self._remote.request("GET", remote_path, query, None)
            if status != 200:
                if path not in self._remote_failed:
                    self._remote_failed.add(path)
                    logger.warning(
                        "flua: HC3 fetch for %s failed (HTTP %s) — "
                        "serving the sim's struct",
                        remote_path,
                        status,
                    )
                return None
            self._remote_cache[path] = (data, status)
        return self._remote_cache[path]

    def _restart_qa(self, qa_id: int) -> bool:
        """Real QA restart for POST /plugins/restartDevice: the HC3 restarts
        the plugin process; flua re-runs the code (timers cancelled, onInit
        runs again). False when the id is not a running QA."""
        if self._engine is None:
            return False
        try:
            self._engine.restart_qa(qa_id)
        except ValueError:
            return False
        return True

    def _fetch(self, url: str) -> tuple[int | None, str, dict]:
        """Server-side fetch for GET /proxy?url=... through the engine's
        HTTP client."""
        if self._engine is None:
            return None, "", {}
        return self._engine.fetch_url(url)

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

        Serialized against other dispatches: remote-mode QA calls arrive
        from worker threads while the pump mutates the sim in between.
        """
        with self._dispatch_lock:
            data, status = self._dispatch(method, url, body, qa_id, external)
        self._trace_api(method, url, body, status, qa_id)
        return data, status

    def _dispatch(
        self,
        method: str,
        url: str,
        body: Any = None,
        qa_id: int | None = None,
        external: bool = False,
    ) -> tuple[Any, int]:
        if self._engine is not None:
            self._engine.mark_db_dirty()  # may mutate the sim (--%%db:+)
        method = method.upper()
        segments, query = parse_url(url)
        if segments[:1] == ["quickApp"]:
            # /api/quickApp/* — QA source files + export, engine-backed
            # (they mutate the running QAs, not the static sim state)
            return self._quickapp(method, segments, body)
        path = "/" + "/".join(segments)
        # A QA pinned offline (--%%mode:offline) never sees the HC3: its
        # remote hook is None, so handlers (list unions, proxy forwarding)
        # and the 404 fallback all stay in the sim.
        offline = self._engine is not None and self._engine.qa_is_offline(qa_id)
        remote_hook = self._remote_hook if (self._remote is not None and not offline) else None
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
                remote=remote_hook,
                remote_cached=self._remote_cached if remote_hook is not None else None,
                restart_qa=self._restart_qa,
                fetch=self._fetch,
                helper=self._helper_bridge if remote_hook is not None else None,
            )
            try:
                data, status = handler(self.state, req)
            except Exception:
                logger.exception("api handler failed for %s %s", method, url)
                return None, 500
            flua_id = (
                len(segments) >= 2
                and segments[0] in ("devices", "plugins")
                and self.state.is_flua_id(segments[1])
            )
            if data is None and status == 404 and remote_hook is not None and not flua_id:
                # the sim doesn't own this entity — ask the real HC3. The
                # variables endpoints it refuses to external REST callers
                # go through the FluaHelper QA (the controller's local
                # context) instead of the plain REST transport.
                if _variables_via_helper(method, path):
                    if self._helper_bridge is not None:
                        return self._helper_bridge(method, path, body)
                    return None, 404
                return self._remote.request(method, path, query, body)
            return data, status
        logger.debug("no offline route for %s %s", method, url)
        flua_id = (
            len(segments) >= 2
            and segments[0] in ("devices", "plugins")
            and self.state.is_flua_id(segments[1])
        )
        if remote_hook is not None and not flua_id:
            # online mode: anything the sim doesn't own goes to the real HC3
            return self._remote.request(method, path, query, body)
        return None, 404

    def dispatch_hc3(self, method: str, url: str, body: Any = None) -> tuple[Any, int]:
        """api.hc3.*: force the REAL HC3, bypassing the hybrid dispatch —
        used by fibaro.callhc3 and test code that wants ground-truth data.
        Without a remote backend (local mode) the sim stands in."""
        with self._dispatch_lock:
            data, status = self._dispatch_hc3(method, url, body)
        self._trace_api(method, url, body, status, None, hc3=True)
        return data, status

    # -- run tracing (--trace api|ui): one structured event per dispatched
    # call, so agents can follow every api.* the QA makes (URL, status, and
    # the request body — the arguments that usually go wrong)
    _UI_TRACE_RE = re.compile(r"/plugins/callUIEvent|/devices/\d+/action/|/devices/groupAction/")

    def _trace_api(
        self,
        method: str,
        url: str,
        body: Any,
        status: int,
        qa_id: int | None,
        hc3: bool = False,
    ) -> None:
        engine = self._engine
        if engine is None:
            return
        if qa_id is None and not hc3:
            return  # engine-internal traffic (seeding, restores) stays quiet
        category = "ui" if self._UI_TRACE_RE.search(url) else "api"
        data: dict[str, Any] = {"method": method, "url": url, "status": status}
        if body is not None:
            data["body"] = _trace_body(body)
        if hc3:
            data["hc3"] = True
        engine.trace_event(category, qa_id, data)

    def _dispatch_hc3(self, method: str, url: str, body: Any = None) -> tuple[Any, int]:
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
                # POST /quickApp — create a QuickApp device (empty main);
                # 201 like the live HC3's upload
                device = self._engine.create_qa(body)
                return (device, 201) if device is not None else (None, 400)
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
        """Accept the import endpoint's bodies: the documented base64 body
        ({"file": "<base64>"}), a direct .fqa table (flua convenience), and
        — like the real HC3 — a multipart/form-data body (the web UI's wire
        format: a ``file`` part carrying the .fqa JSON). The controller's
        parser is strictly multipart; a raw JSON body there dies with a 500."""
        if isinstance(body, (str, bytes)):
            return _fqa_from_multipart(body)
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
