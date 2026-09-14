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
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__, messages
from .clock import parse_start_time
from .config import parse_annotations, peek_offline, split_annotations
from .engine import LuaEngine

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flua",
        description="Minimal Lua engine on lupa + asyncio with cooperative timers.",
    )
    parser.add_argument("scripts", nargs="*", help="Lua QuickApp files to run (each isolated)")
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
        help="0 = run until exit(); N>0 = at least N virtual s, then exit "
        "when idle; N<0 = exactly abs(N) virtual s",
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
        "--start",
        metavar="WHEN",
        help="virtual start time, e.g. '2027/10/6 12:00:20' (defaults to now)",
    )
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="always",
        help="ANSI colors on QA log lines: always (default), auto (terminal only), never",
    )
    parser.add_argument(
        "--api",
        choices=["local", "remote"],
        default=None,
        help="explicit REST API backend. Default: the main QA's --%%offline:true "
        "selects offline; otherwise online when HC3 credentials exist in the "
        "environment, else offline",
    )
    parser.add_argument(
        "--seed",
        metavar="FILE",
        help="JSON file seeding the simulated HC3: devices, rooms, scenes, globalVariables",
    )
    parser.add_argument(
        "--nogreet",
        action="store_true",
        help="skip the startup greeting line",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="static checks only (syntax, --%% directives, deprecated APIs); do not run",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="restart QAs when their files change (mtime polling, no dependencies)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
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
) -> tuple[float, float | None, float | None]:
    """Resolve virtual-time settings; CLI flags win over global config.

    Global config keys: speed, instant, maxhours, or the combined
    --%%time:speed=N,instant=true,hours=H.
    Returns (speed, max_virtual_hours, start_epoch_seconds).
    """
    time_raw = global_config.get("time")
    time_cfg = time_raw if isinstance(time_raw, dict) else {}

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

    # virtual start time: --start flag > bare --%%time:2027/10/6 12:00:20 >
    # the combined form's start= subparameter
    start_text = args.start
    if start_text is None and isinstance(time_raw, str):
        start_text = time_raw  # bare --%%time:<when> form
    elif start_text is None:
        start_text = time_cfg.get("start")
    start_epoch = None
    if start_text:
        try:
            start_epoch = parse_start_time(str(start_text))
        except ValueError as exc:
            parser.error(str(exc))

    return speed, max_hours, start_epoch


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
    if run_for is None:
        return engine.has_pending_work()  # graceful: exit when all work is done
    if run_for == 0:
        return True  # run until exit()
    # --run-for measures VIRTUAL seconds (the engine's clock): with --speed/
    # --instant it counts simulated time. Instant mode advances virtual time
    # only when timers fire, so a run with nothing left to fire would never
    # reach N — the wall bound keeps such runs from hanging.
    virtual = engine.clock.elapsed()
    wall = time.monotonic() - start
    if run_for > 0:
        # at least N virtual seconds, then exit when idle
        return (virtual < run_for and wall < run_for) or engine.has_pending_work()
    # fixed duration: exactly N virtual seconds (never longer than N wall)
    return virtual < -run_for and wall < -run_for


async def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    global_config, qa_specs = _load_qas(parser, args)

    if args.check:
        return _check_cli(parser, args)

    speed, max_hours, start_epoch = _resolve_runtime(parser, args, global_config)
    seed: dict[str, Any] | None = None
    if args.seed:
        try:
            seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
        except OSError as exc:
            parser.error(f"cannot read seed file: {exc}")
        except ValueError as exc:
            parser.error(f"invalid seed JSON: {exc}")
        if not isinstance(seed, dict):
            parser.error("seed file must contain a JSON object")
    try:
        # plua behavior: PEEK at the main QA file's raw header for
        # --%%offline:true (before the engine starts — the standard parse
        # runs after); an explicit --api flag always wins. Without either,
        # the engine resolves: online if HC3 credentials exist, else offline.
        api_mode = args.api
        if api_mode is None and qa_specs:
            main_path, main_code, _ = qa_specs[0]
            if main_path is not None and Path(main_path).exists():
                main_source = Path(main_path).read_text(encoding="utf-8")
            else:
                main_source = main_code or ""
            if peek_offline(main_source):
                api_mode = "local"
        engine = LuaEngine(
            start=start_epoch,
            speed=speed,
            config=global_config,
            color=args.color,
            api_mode=api_mode,
            seed=seed,
        )
    except ValueError as exc:
        parser.error(str(exc))
    await engine.start()
    if not args.nogreet:
        # route the greeting through the message queue so it shares the
        # pump's FIFO with all QA output — guaranteed to appear first
        engine.post(
            messages.log(
                "info",
                f"flua {__version__}, {engine.lua_version()}, Python {sys.version.split()[0]}",
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

    # -e code that is a debugger bootstrap (the VS Code mobdebug extension
    # launches interpreters with -l package -e "<bootstrap>") must NOT become
    # a QA — otherwise the user's script would get QA id 5001 instead of 5000.
    # It runs as a main-state preamble before the scripts.
    preambles = [spec for spec in qa_specs if spec[0] is None and "mobdebug" in (spec[1] or "")]
    qa_specs = [spec for spec in qa_specs if spec not in preambles]
    for _path, code, _params in preambles:
        engine.enqueue_outbound(messages.run_preamble(code or ""))

    watch_paths: dict[str, set[int]] = {}
    for path, code, local_params in qa_specs:
        qa_config = dict(global_config)
        qa_config.update(local_params)
        arg0 = path if path is not None else "flua"
        try:
            qa_id = engine.start_qa(path, code, qa_config, arg0)
        except ValueError as exc:
            parser.error(str(exc))
        if args.watch:
            info = engine.qa_info(qa_id)
            for f in info["files"] if info else []:
                if f.get("path"):
                    watch_paths.setdefault(f["path"], set()).add(qa_id)

    if args.watch:
        args.run_for = 0  # stay alive until exit() or Ctrl-C
        mtimes = {p: os.path.getmtime(p) for p in watch_paths if os.path.exists(p)}

        async def watch_loop() -> None:
            while engine.is_running():
                await asyncio.sleep(0.5)
                for path, qa_ids in watch_paths.items():
                    try:
                        mtime = os.path.getmtime(path)
                    except OSError:
                        continue
                    if mtime != mtimes.get(path):
                        mtimes[path] = mtime
                        await asyncio.sleep(0.2)  # let editors finish writing
                        for qa_id in sorted(qa_ids):
                            engine.restart_qa(qa_id)
                            engine.post(
                                messages.log(
                                    "info",
                                    f"[watch] restarted QA {qa_id} ({Path(path).name})",
                                )
                            )

        asyncio.create_task(watch_loop(), name="flua-watch")

    start = time.monotonic()
    max_virtual_seconds = None if max_hours is None else max_hours * 3600.0
    # cap simulated time at the run limit (fixed --run-for, --%%maxhours) so
    # instant mode stops firing exactly there instead of overshooting
    horizon: float | None = max_virtual_seconds
    if args.run_for is not None and args.run_for < 0:
        horizon = -args.run_for if horizon is None else min(horizon, -args.run_for)
    if horizon is not None:
        engine.limit_run(horizon)
    try:
        while _keep_running(engine, args.run_for, start, max_virtual_seconds):
            await asyncio.sleep(0.05)
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            await engine.stop()
    if max_virtual_seconds is not None and engine.clock.elapsed() >= max_virtual_seconds:
        print(f"flua: virtual time limit reached ({max_hours}h)", file=sys.stderr)
    return engine.exit_code


def _check_cli(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Static checks for every QA file / -e code; exit 1 only on errors."""
    from .check import check_file, check_source

    engine = LuaEngine()
    lua = engine.lua_runtime()
    findings: list[str] = []
    if args.code is not None:
        findings += check_source(args.code, "<command line>", lua)
    for script in args.scripts:
        path = Path(script)
        if not path.exists():
            parser.error(f"cannot open {script}: no such file")
        findings += check_file(str(path.resolve()), lua)
    if not findings:
        print("ok")
        return 0
    for line in findings:
        print(line)
    return 1 if any(": error:" in line for line in findings) else 0


def _export_cli(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """flua export script.lua -o out.fqa — the deploy artifact, without running."""
    path = Path(args.script)
    if not path.exists():
        parser.error(f"cannot open {args.script}: no such file")
    source = path.read_text(encoding="utf-8")
    _, local_params = split_annotations(parse_annotations(source))
    engine = LuaEngine()
    qa_id = engine._prepare_qa(str(path.resolve()), None, local_params, str(path.resolve()))
    fqa = engine.qa_export(qa_id)
    output = Path(args.output) if args.output else path.with_suffix(".fqa")
    output.write_text(json.dumps(fqa, indent=2) + "\n", encoding="utf-8")
    print(f"exported {len(fqa['files'])} files to {output}")
    return 0


def _unpack_cli(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """flua unpack package.fqa -d dir/ — turn an HC3 export into a flua project."""
    path = Path(args.package)
    if not path.exists():
        parser.error(f"cannot open {args.package}: no such file")
    try:
        fqa = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        parser.error(f"invalid fqa JSON: {exc}")
    if not isinstance(fqa, dict):
        parser.error("fqa file must contain a JSON object")
    directory = args.directory or Path(str(fqa.get("name") or "quickapp")).name
    os.makedirs(directory, exist_ok=True)
    engine = LuaEngine()
    main_path, err = engine.fqa_to_files(fqa, directory)
    if err is not None:
        parser.error(f"cannot unpack: {err}")
    print(f"unpacked to {directory}/ (main: {main_path})")
    return 0


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
    raw = sys.argv[1:] if argv is None else argv
    # Tool commands (flua export/unpack) get their own parsers — argparse
    # subparsers would swallow the run mode's first positional script.
    if raw and raw[0] in ("export", "unpack"):
        return _tool_main(raw)
    parser = _build_parser()
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


def _tool_parser(command: str) -> argparse.ArgumentParser:
    if command == "export":
        parser = argparse.ArgumentParser(
            prog="flua export", description="Export a QA file as a .fqa package."
        )
        parser.add_argument("script", help="the QA main file")
        parser.add_argument(
            "-o",
            "--output",
            metavar="FILE",
            help="output .fqa path (default: <name>.fqa next to the script)",
        )
        return parser
    parser = argparse.ArgumentParser(
        prog="flua unpack", description="Unpack a .fqa into a flua project directory."
    )
    parser.add_argument("package", help="the .fqa file")
    parser.add_argument(
        "-d",
        "--directory",
        metavar="DIR",
        help="target directory (default: the QA name)",
    )
    return parser


def _tool_main(raw: list[str]) -> int:
    command, rest = raw[0], raw[1:]
    tool = _tool_parser(command)
    args = tool.parse_args(rest)
    if command == "export":
        return _export_cli(tool, args)
    return _unpack_cli(tool, args)


if __name__ == "__main__":
    sys.exit(main())
