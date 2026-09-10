"""The ``_PY`` table — the only surface Lua sees into Python.

Two kinds of functions live here:

- ``post(msg)`` — append a message to the inbound queue. Never blocks, never
  calls Lua; the result (if any) comes back later through ``_PY.dispatch``.
- Pure synchronous helpers (``now()``, ``version()``) that never call back
  into Lua and are therefore safe at any call depth.

``lua/init.lua`` adds the Lua half of the protocol: the callback registry,
the timer globals, the ``print`` override, and ``_PY.dispatch``.
"""

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
        if keys and all(isinstance(key, int) and key >= 1 for key in keys) and sorted(
            keys
        ) == list(range(1, len(keys) + 1)):
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
    py["note_debugger_pause"] = engine.clock.note_pause
    py["version"] = lambda: __version__
    py["color_enabled"] = engine.color_enabled

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

    init_path = runtime_dir / "init.lua"
    lua.execute(f"loadfile({_lua_quote(str(init_path))})()")
    # The global config lives on the Lua-side API table _FLUA (created by
    # init.lua), not on the Python bridge.
    lua.globals()["_FLUA"]["config"] = lua.table_from(engine.config, recursive=True)
