"""The ``_PY`` table — the only surface Lua sees into Python.

Two kinds of functions live here:

- ``post(msg)`` — append a message to the inbound queue. Never blocks, never
  calls Lua; the result (if any) comes back later through ``_PY.dispatch``.
- Pure synchronous helpers (``now()``, ``version()``) that never call back
  into Lua and are therefore safe at any call depth.

``lua/init.lua`` adds the Lua half of the protocol: the callback registry,
the timer globals, the ``print`` override, and ``_PY.dispatch``.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from . import __version__

if TYPE_CHECKING:
    from .engine import LuaEngine


def _lua_quote(path: str) -> str:
    return "'" + path.replace("\\", "/").replace("'", "\\'") + "'"


def _is_lua_table(obj: object) -> bool:
    # lupa LuaTable proxies support .items() but are not dicts
    return hasattr(obj, "items") and not isinstance(obj, dict)


def lua_to_python(value: object) -> object:
    """Convert a lupa value to plain JSON-compatible Python data.

    Lua tables arrive in Python as lupa proxies, not dicts. Messages must be
    converted at the post() boundary so the engine only ever sees plain data.
    """
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if _is_lua_table(value):
        items = list(value.items())
        keys = [key for key, _ in items]
        if (
            keys
            and all(isinstance(key, int) and key >= 1 for key in keys)
            and sorted(keys) == list(range(1, len(keys) + 1))
        ):
            # array-shaped table -> list
            return [lua_to_python(val) for _, val in sorted(items)]
        result = {}
        for key, val in items:
            python_key = key.decode("utf-8") if isinstance(key, bytes) else key
            result[python_key] = lua_to_python(val)
        return result
    if isinstance(value, (list, tuple)):
        return [lua_to_python(item) for item in value]
    return value


def _json_to_python(value: object, lua: object) -> object:
    """lupa value -> JSON-compatible Python, honoring json.util.InitArray.

    Like lua_to_python, but a table marked with json.util.InitArray (a
    metatable with __isArray = true) encodes as an array even when empty —
    the one case the 1..n key heuristic cannot decide ({} vs []). Reads the
    metatable through Lua's C builtin getmetatable, which lupa allows from
    Python callbacks.
    """
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if _is_lua_table(value):
        items = list(value.items())
        keys = [key for key, _ in items]
        mt = lua.globals().getmetatable(value)
        marked = mt is not None and bool(getattr(mt, "__isArray", False))
        if marked:
            int_keys = sorted(key for key in keys if isinstance(key, int) and key >= 1)
            return [_json_to_python(value[key], lua) for key in int_keys]
        if (
            keys
            and all(isinstance(key, int) and key >= 1 for key in keys)
            and sorted(keys) == list(range(1, len(keys) + 1))
        ):
            # array-shaped table -> list
            return [_json_to_python(val, lua) for _, val in sorted(items)]
        result = {}
        for key, val in items:
            python_key = key.decode("utf-8") if isinstance(key, bytes) else key
            result[python_key] = _json_to_python(val, lua)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_to_python(item, lua) for item in value]
    return value


def install_bindings(engine: "LuaEngine") -> None:
    """Install the _PY table into the engine's Lua globals and run init.lua."""
    lua = engine.lua_runtime()

    def post(msg: object) -> None:
        engine.post(lua_to_python(msg))

    py = lua.table()
    py["post"] = post
    # Virtual engine time (see clock.py): realtime by default, accelerated
    # with --speed, frozen during debugger pauses, jumping with --instant.
    py["now"] = lambda: engine.clock.time
    py["vtime"] = lambda: engine.clock.time
    py["vclock"] = lambda: engine.clock.elapsed()
    py["note_debugger_pause"] = engine.note_debugger_pause
    py["log"] = engine.log_line
    py["getenv"] = engine.env.get
    py["version"] = lambda: __version__
    py["color_enabled"] = engine.color_enabled

    # JSON for QA code and mobdebug's VSCODE protocol (json.lua delegates
    # here). _json_to_python honors json.util.InitArray; lua_to_python (the
    # message path) stays heuristic-only on purpose.
    def to_json(value: object) -> str:
        return json.dumps(_json_to_python(value, lua))

    def parse_json(text: str | bytes) -> object:
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        return lua.table_from(json.loads(text), recursive=True)

    # HC3 REST bridge: api.get/post/put/delete -> (data, status). Synchronous
    # like the real HC3 builtins; offline it dispatches to the simulated HC3
    # (running QAs + seeded state), online mode will route to the real HC3.
    def api_call(
        method: str, url: str, body: object, qa_id: int | None = None
    ) -> tuple[object, int]:
        if bool((engine.config.get("debug") or {}).get("api")):
            engine.debug_log(f"api {method.upper()} {url}")
        data, status = engine.api.dispatch(method, url, lua_to_python(body), qa_id=qa_id)
        if data is None:
            return None, status
        if not isinstance(data, (dict, list, tuple)):
            return data, status  # scalars cross the bridge natively
        return lua.table_from(data, recursive=True), status

    # api.hc3.*: the real HC3 directly (no hybrid dispatch) — callhc3 and
    # test code; falls back to the local sim without a remote backend.
    def api_hc3(method: str, url: str, body: object) -> tuple[object, int]:
        if bool((engine.config.get("debug") or {}).get("api")):
            engine.debug_log(f"api.hc3 {method.upper()} {url}")
        data, status = engine.api.dispatch_hc3(method, url, lua_to_python(body))
        if data is None:
            return None, status
        if not isinstance(data, (dict, list, tuple)):
            return data, status
        return lua.table_from(data, recursive=True), status

    # Enriched device for a QA (type skeleton + config, registered by the
    # engine at start_qa). The Lua bootstrap builds the QuickApp instance
    # from it, so the instance matches what the API serves.
    def device_for(qa_id: int) -> object:
        device = engine.api.state.devices.get(int(qa_id))
        if device is None:
            return None
        return lua.table_from(device, recursive=True)

    # Dynamic QA loading (dev/test convenience): install and run another QA
    # from a file (its --%% annotations are parsed) or from inline code.
    # File loading returns (qa_id, nil) or (nil, error message).
    def load_qa_file(path: str) -> tuple[object, object]:
        qa_id, err = engine.load_qa_file(path)
        return qa_id, err

    def qa_temp_file(code: str) -> str:
        return engine.qa_temp_file(code)

    # net.UDPSocket: the constructor binds an ephemeral UDP socket
    # synchronously (bind is instant, no network I/O); send/receive go
    # through the message pump like the other net classes.
    def udp_open(broadcast: bool, timeout: float | None) -> tuple[object, object, object]:
        ok, conn, port = engine.qa_udp.open(0, bool(broadcast), timeout)
        if ok:
            return True, conn, port
        return False, conn, None

    py["to_json"] = to_json
    py["parse_json"] = parse_json
    py["api"] = api_call
    py["api_hc3"] = api_hc3
    py["device_for"] = device_for
    py["load_qa_file"] = load_qa_file
    py["qa_temp_file"] = qa_temp_file
    py["udp_open"] = udp_open
    py["udp_close"] = engine.qa_udp.close
    # net.WebSocketClient: the constructor claims a connection slot
    # synchronously (no I/O); connect/send ride the pump, events come back
    # as wsEvent messages. isOpen/close are instant state operations.
    py["ws_new"] = engine.qa_websockets.new_slot
    py["ws_is_open"] = engine.qa_websockets.is_open
    py["ws_close"] = engine.qa_websockets.close
    # mqtt.* client: the constructor claims a connection slot synchronously
    # (no I/O); ops ride the pump, events come back as mqttEvent messages.
    py["mqtt_new"] = engine.qa_mqtt.new_slot

    # Blocking LuaSocket-compatible TCP calls for mobdebug. These may block
    # the asyncio loop (documented exception — a debugger pause freezes time).
    sc = engine.sync_sockets
    py["tcp_connect"] = sc.connect
    py["tcp_write"] = sc.write
    py["tcp_read"] = sc.read
    py["tcp_close"] = sc.close
    py["tcp_set_timeout"] = sc.set_timeout
    py["tcp_bind"] = sc.bind
    py["tcp_accept"] = sc.accept
    py["tcp_getsockname"] = sc.getsockname

    lua.globals()["_PY"] = py

    # Make the runtime dir require-able: require("socket"), require("mobdebug").
    runtime_dir = Path(__file__).parent / "lua"
    if not runtime_dir.exists():
        raise FileNotFoundError(f"flua runtime missing: {runtime_dir}")
    lua.execute(f"package.path = {_lua_quote(str(runtime_dir))} .. '/?.lua;' .. package.path")
    # The Lua side needs the runtime dir as an absolute fact: QAs may rewrite
    # package.path (the VS Code mobdebug extension's injected bootstrap
    # prepends its own dir), so init.lua must not derive it from package.path.
    py["runtime_dir"] = str(runtime_dir)

    init_path = runtime_dir / "init.lua"
    lua.execute(f"loadfile({_lua_quote(str(init_path))})()")
    # The global config lives on the Lua-side API table _FLUA (created by
    # init.lua), not on the Python bridge.
    lua.globals()["_FLUA"]["config"] = lua.table_from(engine.config, recursive=True)
