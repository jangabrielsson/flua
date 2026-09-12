"""flua CLI — run one or more Lua QuickApps.

Usage::

    flua [options] file1.lua [file2.lua ...]
    flua [options] -e 'code'

Every Lua file is a QuickApp: it runs in its own environment (same Lua
state, isolated globals) with its own timer tracking, and gets ``config`` —
a copy of the global config (CLI flags + global ``--%%`` annotations) plus
its local ``--%%`` annotations. Global config parameters set by a QA file
(speed, instant, maxhours, time) are copied up to the global config — the
last file that sets one wins.
"""

import argparse
import asyncio
import contextlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__, messages
from .config import parse_annotations, split_annotations
from .engine import LuaEngine

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flua",
        description="Minimal Lua engine on lupa + asyncio with cooperative timers.",
    )
    parser.add_argument(
        "scripts", nargs="*", help="Lua QuickApp files to run (each isolated)"
    )
    parser.add_argument(
        "-e",
        "--execute",
        dest="code",
        help="execute Lua code first (then any scripts), like the Lua CLI",
    )
    parser.add_argument(
        "-l",
        metavar="L",
        help="ignored, for Lua CLI compatibility (the VS Code mobdebug "
        "extension launches interpreters with '-l package')",
    )
    parser.add_argument(
        "--run-for",
        type=float,
        default=None,
        metavar="N",
        help="0 = run until exit(); N>0 = at least N s; N<0 = exactly abs(N) s",
    )
    parser.add_argument(
        "--debugger",
        nargs="?",
        const=8172,
        type=int,
        metavar="PORT",
        help="attach the mobdebug remote debugger on PORT (default 8172)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=None,
        metavar="N",
        help="virtual time speed: 1 = realtime, N>0 = N times faster",
    )
    parser.add_argument(
        "--max-hours",
        type=float,
        default=None,
        metavar="H",
        help="stop after H virtual hours (useful for accelerated/instant runs)",
    )
    parser.add_argument(
        "--instant",
        action="store_true",
        help="instant mode: timers fire immediately, os.time() jumps by each delay",
    )
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="always",
        help="ANSI colors on QA log lines: always (default), auto (terminal only), never",
    )
    parser.add_argument(
        "--nogreet",
        action="store_true",
        help="skip the startup greeting line",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="enable debug logging"
    )
    parser.add_argument("--version", action="version", version=f"flua {__version__}")
    return parser


def _load_qas(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[dict[str, Any], list[tuple[str | None, str | None, dict[str, Any]]]]:
    """Return (global_config, qa_specs).

    Each QA spec is (path, code, local_params); path is the resolved file
    path (loadfile, so breakpoints match) or None for -e code. Like the Lua
    CLI, -e code runs before any scripts — the VS Code mobdebug extension
    launches interpreters with -l package -e "<debugger bootstrap>" plus the
    script. Global params from every QA are copied up in file order — the
    last file wins.
    """
    global_config: dict[str, Any] = {}
    specs: list[tuple[str | None, str | None, dict[str, Any]]] = []
    if args.code is not None:
        global_params, local_params = split_annotations(parse_annotations(args.code))
        global_config.update(global_params)
        specs.append((None, args.code, local_params))
    for script in args.scripts:
        path = Path(script)
        if not path.exists():
            parser.error(f"cannot open {script}: no such file")
        source = path.read_text(encoding="utf-8")
        global_params, local_params = split_annotations(parse_annotations(source))
        global_config.update(global_params)  # last file wins
        specs.append((str(path.resolve()), None, local_params))
    if not specs:
        parser.error("no script or -e code given")
    return global_config, specs


def _resolve_runtime(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    global_config: dict[str, Any],
) -> tuple[float, float | None]:
    """Resolve virtual-time settings; CLI flags win over global config.

    Global config keys: speed, instant, maxhours, or the combined
    --%%time:speed=N,instant=true,hours=H.
    Returns (speed, max_virtual_hours).
    """
    time_cfg = global_config.get("time")
    time_cfg = time_cfg if isinstance(time_cfg, dict) else {}

    speed = args.speed
    if speed is None:
        speed = time_cfg.get("speed", global_config.get("speed", 1.0))
    if speed <= 0:
        parser.error("--speed must be > 0 (also for --%%speed annotations)")

    instant = args.instant
    if not instant:
        instant = bool(time_cfg.get("instant", global_config.get("instant", False)))
    if instant:
        speed = float("inf")

    max_hours = args.max_hours
    if max_hours is None:
        max_hours = time_cfg.get("hours", global_config.get("maxhours"))
    if max_hours is not None and max_hours <= 0:
        parser.error("--max-hours must be > 0 (also for --%%maxhours annotations)")

    return speed, max_hours


def _start_debugger(engine: LuaEngine, port: int) -> None:
    """Attach mobdebug before the QAs run. Failures are non-fatal.

    The Lua-side pattern lives in lua/init.lua (`_FLUA.startDebugger`,
    plua-style). While the debugger is paused at a breakpoint, its blocking
    socket receive freezes the asyncio loop, so Lua timers stop — time stands
    still until the debugger resumes the program.
    """
    engine.execute(f"_FLUA.startDebugger('localhost', {int(port)})")


def _keep_running(
    engine: LuaEngine,
    run_for: float | None,
    start: float,
    max_virtual_seconds: float | None,
) -> bool:
    if not engine.is_running():
        return False
    if max_virtual_seconds is not None and engine.clock.elapsed() >= max_virtual_seconds:
        return False  # virtual time limit reached
    elapsed = time.monotonic() - start
    if run_for is None:
        return engine.has_pending_work()  # graceful: exit when all work is done
    if run_for == 0:
        return True  # run until exit()
    if run_for > 0:
        return elapsed < run_for or engine.has_pending_work()
    return elapsed < -run_for  # fixed duration


async def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    global_config, qa_specs = _load_qas(parser, args)
    speed, max_hours = _resolve_runtime(parser, args, global_config)
    engine = LuaEngine(speed=speed, config=global_config, color=args.color)
    await engine.start()
    if not args.nogreet:
        # route the greeting through the message queue so it shares the
        # pump's FIFO with all QA output — guaranteed to appear first
        engine.post(
            messages.log(
                "info",
                f"flua {__version__}, {engine.lua_version()}, "
                f"Python {sys.version.split()[0]}",
            )
        )
    if args.debugger is not None:
        _start_debugger(engine, args.debugger)
    else:
        # Debugger tooling (e.g. the VS Code mobdebug extension) launches the
        # interpreter with MOBDEBUG_PORT set; honor it like the --debugger flag.
        env_port = os.environ.get("MOBDEBUG_PORT")
        if env_port:
            _start_debugger(engine, int(env_port))

    for path, code, local_params in qa_specs:
        qa_config = dict(global_config)
        qa_config.update(local_params)
        arg0 = path if path is not None else "flua"
        engine.start_qa(path, code, qa_config, arg0)

    start = time.monotonic()
    max_virtual_seconds = None if max_hours is None else max_hours * 3600.0
    try:
        while _keep_running(engine, args.run_for, start, max_virtual_seconds):
            await asyncio.sleep(0.05)
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            await engine.stop()
    if (
        max_virtual_seconds is not None
        and engine.clock.elapsed() >= max_virtual_seconds
    ):
        print(f"flua: virtual time limit reached ({max_hours}h)", file=sys.stderr)
    return engine.exit_code


def _normalize_debugger_argv(argv: list[str]) -> list[str]:
    """Let ``--debugger script.lua`` mean the default port (8172).

    ``--debugger`` takes an optional port, but argparse's optional-value
    arguments only use their default when the next token looks like an
    option — so ``flua --debugger script.lua`` would parse the script as the
    port and fail with "invalid int value". When ``--debugger`` is followed
    by a non-option, non-integer token, move the bare flag to the end so the
    script stays a positional and the flag takes its const. An explicit
    ``--debugger PORT script.lua`` (or ``--debugger=PORT``) is untouched.
    """
    out: list[str] = []
    moved: list[str] = []
    i = 0
    while i < len(argv):
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if (
            argv[i] == "--debugger"
            and nxt is not None
            and not nxt.startswith("-")
            and not nxt.isdigit()
        ):
            moved.append(argv[i])
        else:
            out.append(argv[i])
        i += 1
    return out + moved


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    raw = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(_normalize_debugger_argv(raw))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(_run(parser, args))
    except KeyboardInterrupt:
        print("flua: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
