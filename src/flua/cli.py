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
import io
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import __version__, messages
from .api import Api
from .audit import add_arguments as _audit_add_arguments
from .audit import run as _audit_run
from .clock import parse_start_time
from .config import (
    OVERRIDES_FILE,
    expand_includes,
    merge_annotations,
    parse_annotations,
    split_annotations,
)
from .doctor import add_arguments as _doctor_add_arguments
from .doctor import run as _doctor_run
from .engine import LuaEngine
from .http_server import ApiServer
from .record_cli import add_arguments as _record_add_arguments
from .record_cli import run as _record_run
from .test_cli import add_arguments as _test_add_arguments
from .test_cli import run as _test_run
from .tools import run_tool
from .tools.common import build_fqa, default_fqa_output

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flua",
        description="Minimal Lua engine on lupa + asyncio with cooperative timers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "commands:\n"
            "  flua export script.lua -o out.fqa   package a QA project as a .fqa\n"
            "  flua unpack package.fqa -d dir/    unpack a .fqa into a flua project\n"
            "  flua test [paths] --timeout N       run self-asserting test QAs (*_test.lua)\n"
            "  flua doctor [--no-network] [--json] health-check this workspace\n"
            "  flua record -o house.json       capture the real HC3's state + "
            "refreshState events\n"
            "  flua audit [--json]              coverage: HC3 routes and device catalog\n"
            "  flua --tool NAME ...                HC3 file tools (uploadQA, downloadQA,"
            " pack, unpack, setup, newQA, ...; a bare --tool lists them)"
        ),
    )
    parser.add_argument("scripts", nargs="*", help="Lua QuickApp files to run (each isolated)")
    parser.add_argument(
        "-D",
        "--directive",
        action="append",
        default=[],
        metavar="DIRECTIVE",
        help="inject a --%% directive, as if appended to every QA's header "
        "(repeatable; e.g. -D mode:online -D var:x=42) — handy when testing "
        "foreign code without editing it",
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
        help="0 = run until exit(); N>0 = at least N virtual s, then exit "
        "when idle (N wall s is a hard deadline — exit 1 if it cuts the "
        "run short with work pending); N<0 = exactly abs(N) virtual s "
        "(step mode: run until idle, at most abs(N) wall s — timers beyond "
        "N still fire)",
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
        "--step",
        action="store_true",
        help="deterministic deadline-ordered fast-forward (plua speedTime): "
        "the clock advances to each timer's deadline before its callback "
        "runs, one timer at a time — os.time()-relative delay math (event "
        "engines) stays coherent, and the run completes at CPU speed",
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
        help="explicit REST API backend. Default: the main QA's "
        "--%%%%mode:online|proxy selects the real HC3, --%%%%mode:offline "
        "the sim; otherwise OFFLINE (the default — the simulated HC3). "
        "Online needs HC3 credentials in the environment",
    )
    parser.add_argument(
        "--seed",
        metavar="FILE",
        help="JSON file seeding the simulated HC3: devices, rooms, scenes, globalVariables",
    )
    parser.add_argument(
        "--replay",
        metavar="FILE",
        help="replay a recorded house session (flua record): seed the sim with "
        "its devices and fire its refreshState events on the virtual timeline",
    )
    parser.add_argument(
        "--tool",
        "-t",
        dest="tool",
        metavar="TOOL",
        help="run a tool command instead of QAs: downloadQA <id>, "
        "uploadQA <name|main.lua>, updateQA <id> <script> (HC3 credentials "
        "required), icons download (icon cache); a bare --tool lists the "
        "installed tools",
    )
    parser.add_argument(
        "--nogreet",
        action="store_true",
        help="skip the startup greeting line",
    )
    parser.add_argument(
        "--log",
        choices=["text", "json"],
        default="text",
        help="QA log format: human text (default) or JSON lines "
        "({time, level, tag, qaid, msg}) — machine-readable for agents",
    )
    parser.add_argument(
        "--logfile",
        metavar="FILE",
        default=None,
        help="write a copy of the log to FILE (appended; ANSI colors stripped; "
        "JSON lines with --log json)",
    )
    parser.add_argument(
        "--syslog",
        metavar="FILE",
        default=None,
        help="append every structured system/crash event as one JSON line to FILE "
        "(the complete history; /flua/systemLog is the bounded in-memory buffer)",
    )
    parser.add_argument(
        "--trace",
        metavar="LIST",
        default="",
        help="extra structured run traces for agents, as 'event: trace' lines in "
        "the same channel as --syslog: comma list of api, ui, net, timer "
        "(or 'all') — api.* calls with status+bodies, incoming actions and "
        "UI events, net requests/results, and timer starts/expiries",
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="print the installed examples directory and exit",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="static checks only (syntax, --%%%% directives, deprecated APIs); do not run",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="restart QAs when their files change (mtime polling, no dependencies)",
    )
    parser.add_argument(
        "--ui",
        nargs="?",
        const=8090,
        type=int,
        default=None,
        metavar="PORT",
        help="serve the UI viewer and the simulated HC3 API over HTTP (default "
        "port 8090). The viewer is served at http://127.0.0.1:PORT/ — open "
        "that URL in a browser. With no --run-for the run stays up until "
        "Ctrl-C, so the viewer keeps its API even after the QA's timers "
        "drain. A busy port falls back to the next free one (the effective "
        "port is printed at startup)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    parser.add_argument("--version", action="store_true", help="print the flua version and exit")
    parser.add_argument(
        "--machine",
        action="store_true",
        help="with --version: one JSON line (version, lua, python) for agents/installers",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="with --check: machine-readable findings (JSON on stdout)",
    )
    return parser


# Temp dirs holding CLI-unpacked .fqa packages; registered with the engine
# at startup (cleaned at stop). See _load_qas.
_FQA_UNPACK_DIRS: list[str] = []


def _unpack_fqa_script(
    parser: argparse.ArgumentParser, path: Path
) -> tuple[str, dict[str, Any]]:
    """Unpack a .fqa package into a temp dir; returns (main_path, fqa).
    Uses the same machinery as the upload path (engine.fqa_to_files), so the
    regenerated --%% header (name/type/properties/UI/--%%file) drives the
    standard pipeline. The fqa dict comes back so callers can apply package
    metadata the header cannot express (initialInterfaces)."""
    try:
        raw = path.read_text(encoding="utf-8")
        body = json.loads(raw)
    except (OSError, ValueError) as exc:
        parser.error(f"cannot open {path}: {exc}")
    fqa = Api._parse_fqa_body(body)
    if fqa is None or not isinstance(fqa.get("files"), list):
        parser.error(f"cannot open {path}: not a .fqa package (no files list)")
    base = os.path.join(tempfile.gettempdir(), f"flua-qa-files-{os.getpid()}")
    os.makedirs(base, exist_ok=True)
    directory = tempfile.mkdtemp(prefix="cli-fqa-", dir=base)
    main_path, err = LuaEngine.fqa_to_files(fqa, directory)
    if err is not None or main_path is None:
        parser.error(f"cannot open {path}: {err or 'package has no main file'}")
    _FQA_UNPACK_DIRS.append(base)
    return main_path, fqa


def _load_qas(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[dict[str, Any], list[tuple[str | None, str | None, dict[str, Any]]]]:
    """Return (global_config, qa_specs).

    Each QA spec is (path, code, local_params); path is the resolved file
    path (loadfile, so breakpoints match) or None for -e code. Like the Lua
    CLI, -e code runs before any scripts — the VS Code mobdebug extension
    launches interpreters with -l package -e "<debugger bootstrap>" plus the
    script. Global params from every QA are copied up in file order — the
    last file wins. A ``*.fqa`` script argument is unpacked first (a temp
    dir, cleaned at engine stop) and its generated main runs like a normal
    project — so downloaded/packed fqas are directly runnable. A
    ``.flua-directives`` file next to each CLI path (for a .fqa, next to
    the package itself) is merged the same way as -D: it wins over the
    QA's own directives, -D wins over it.
    """
    global_config: dict[str, Any] = {}
    specs: list[tuple[str | None, str | None, dict[str, Any]]] = []
    _FQA_UNPACK_DIRS.clear()
    # -D/--directive: injected as if appended to every QA's header (the
    # injected directives win over the file's own)
    injected: dict[str, Any] | None = None
    for entry in args.directive:
        if not isinstance(entry, str) or not entry.strip():
            parser.error("-D needs a directive string, e.g. -D mode:online")
        annotations = parse_annotations("--%%" + entry)
        injected = annotations if injected is None else merge_annotations(injected, annotations)
    if args.code is not None:
        annotations = parse_annotations(args.code)
        if injected is not None:
            annotations = merge_annotations(annotations, injected)
        global_params, local_params = split_annotations(annotations)
        global_config.update(global_params)
        specs.append((None, args.code, local_params))
    for script in args.scripts:
        path = Path(script)
        if not path.exists():
            parser.error(f"cannot open {script}: no such file")
        # the override file is discovered next to the path given on the CLI —
        # for a .fqa, the package's own directory (never inside it), not the
        # unpack temp dir
        override_dir = path.parent
        fqa_meta: dict[str, Any] | None = None
        if path.suffix.lower() == ".fqa":
            main_path, fqa_meta = _unpack_fqa_script(parser, path)
            path = Path(main_path)
        source = path.read_text(encoding="utf-8")
        try:
            annotations = expand_includes(parse_annotations(source), path.parent)
        except ValueError as exc:
            parser.error(f"error in {script}: {exc}")
        # .flua-directives, next to the main file: the same directive syntax
        # as a QA header, applied like -D (the file wins over the QA's own
        # directives and its --%%include defaults; -D still wins over the
        # file). Zero-config testing of foreign QAs from VS Code — no QA
        # edits, no launch.json edits.
        override_path = override_dir / OVERRIDES_FILE
        if override_path.is_file():
            try:
                override_source = override_path.read_text(encoding="utf-8")
            except OSError as exc:
                parser.error(f"cannot read overrides file {override_path}: {exc}")
            annotations = merge_annotations(annotations, parse_annotations(override_source))
        if injected is not None:
            annotations = merge_annotations(annotations, injected)
        global_params, local_params = split_annotations(annotations)
        if fqa_meta is not None:
            interfaces = fqa_meta.get("initialInterfaces")
            if isinstance(interfaces, list) and interfaces:
                # package metadata the --%% header cannot express; the engine
                # applies it to the device at load (_prepare_qa)
                local_params["initialInterfaces"] = list(interfaces)
        global_config.update(global_params)  # last file wins
        specs.append((str(path.resolve()), None, local_params))
    if not specs:
        parser.error("no script or -e code given")
    return global_config, specs


def _resolve_runtime(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    global_config: dict[str, Any],
) -> tuple[float, bool, float | None, float | None]:
    """Resolve virtual-time settings; CLI flags win over global config.

    Global config keys: speed, step, instant, maxhours, or the combined
    --%%time:speed=N,instant=true,step=true,hours=H.
    Returns (speed, step, max_virtual_hours, start_epoch_seconds).
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

    step = args.step
    if not step:
        step = bool(time_cfg.get("step", global_config.get("step", False)))
    if step and instant:
        parser.error("--step and --instant are mutually exclusive time modes")
    if step and (args.speed is not None or "speed" in time_cfg):
        parser.error("--step cannot be combined with --speed (the clock jumps by deadlines)")
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

    return speed, step, max_hours, start_epoch


def _start_debugger(engine: LuaEngine, port: int) -> None:
    """Attach mobdebug before the QAs run. Failures are non-fatal.

    The Lua-side pattern lives in lua/init.lua (`_FLUA.startDebugger`). While
    the debugger is paused at a breakpoint, its blocking socket receive
    freezes the asyncio loop, so Lua timers stop — time stands still until
    the debugger resumes the program.
    """
    engine.execute(f"_FLUA.startDebugger('localhost', {int(port)})")


def _keep_running(
    engine: LuaEngine,
    run_for: float | None,
    start: float,
    max_virtual_seconds: float | None,
    ui_keepalive: bool = False,
) -> bool:
    if not engine.is_running():
        return False
    if max_virtual_seconds is not None and engine.clock.elapsed() >= max_virtual_seconds:
        return False  # virtual time limit reached
    if run_for is None:
        if ui_keepalive:
            return True  # interactive UI session: run until interrupted (Ctrl-C)
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
        # at least N virtual seconds, then exit when idle — and N WALL
        # seconds is a hard deadline: an open SSE stream (never idle) or a
        # keep-alive QA must not run past it
        if wall >= run_for:
            return False
        return virtual < run_for or engine.has_pending_work()
    # fixed duration: exactly N virtual seconds (never longer than N wall)
    if engine.clock.step:
        # step mode advances only by deadline jumps: "exactly N virtual
        # seconds" is unreachable when the timers drain — the wall cap is
        # the hard stop, and the CLI loop decides the idle exit (with a
        # settle streak, so an in-flight timer re-arm wins over the exit)
        return wall < -run_for
    return virtual < -run_for and wall < -run_for


async def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.check:
        # static checks only: skip the QA load entirely (its annotation parse
        # would log the runtime warnings --check reports itself)
        return _check_cli(parser, args)

    global_config, qa_specs = _load_qas(parser, args)
    if args.watch:
        # watch mode survives QA boot errors: the flag rides the global
        # config into every QA's _FLUA.config, and the bootstrap's error
        # branches log + leave the QA dead instead of exiting the engine —
        # the user fixes the file and the next save restarts it
        global_config["watch"] = True

    speed, step, max_hours, start_epoch = _resolve_runtime(parser, args, global_config)
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
    # --%%db (from the main QA's directives): seeds the sim like --seed and,
    # with the + variant, persists emulator state back to the file. The
    # directive wins over the --seed flag.
    db_path: str | None = None
    db_persist = False
    replay_path: str | None = None
    location: dict[str, Any] | None = None
    for main_path, _main_code, main_params in qa_specs:
        if main_path is None:
            continue
        db_cfg = main_params.get("db")
        if isinstance(db_cfg, dict) and db_cfg.get("path"):
            db_path = str(Path(db_cfg["path"]).resolve())
            db_persist = bool(db_cfg.get("persist"))
            seed = None
        replay_cfg = main_params.get("replay")
        if isinstance(replay_cfg, str) and replay_cfg:
            replay_path = str(Path(replay_cfg).resolve())
        loc_cfg = main_params.get("location")
        if isinstance(loc_cfg, dict):
            # --%%location:latitude=N,longitude=N pins the sim's location
            location = loc_cfg
        break
    if args.replay:
        # the CLI flag wins over a --%%replay directive
        replay_path = str(Path(args.replay).resolve())
    try:
        # The engine mode follows the MAIN QA's directives (its header over
        # any --%%include'd defaults) — --%%mode:offline selects the sim,
        # --%%mode:online|proxy the HC3. An explicit --api flag always
        # wins, and the default (no directive anywhere) is OFFLINE — online
        # is opt-in (docs/decisions/0001).
        api_mode = args.api
        if api_mode is None and qa_specs:
            # the FIRST spec may be an injected -e bootstrap (the mobdebug
            # extension launches -e "<bootstrap>" <script>): skip to the main
            # file spec
            for main_path, _main_code, main_params in qa_specs:
                if main_path is None:
                    continue
                mode = main_params.get("mode")
                if mode == "offline":
                    api_mode = "local"
                elif mode in ("online", "proxy"):
                    api_mode = "remote"
                break
        if args.api == "remote":
            # an explicit --api remote wins over the MAIN QA's
            # --%%mode:offline pin too (its mode drove the engine above;
            # the flag overrides it). Secondary QAs' pins stay — per-QA
            # pinning is their documented feature.
            for main_path, _main_code, main_params in qa_specs:
                if main_path is None:
                    continue
                if main_params.get("offline"):
                    main_params["mode"] = "online"  # _apply_mode clears the pin
                break
        if api_mode is None:
            api_mode = "local"  # default: offline (the sim) — online is opt-in
        engine = LuaEngine(
            start=start_epoch,
            speed=speed,
            step=step,
            config=global_config,
            color=args.color,
            api_mode=api_mode,
            seed=seed,
            db_path=db_path,
            db_persist=db_persist,
            replay_path=replay_path,
            location=location,
            # --%%trace (global directive) is the declarative form of
            # --trace; the CLI flag wins
            trace=args.trace or str(global_config.get("trace") or ""),
        )
        engine.set_log_mode(args.log, args.logfile)
        # --%%syslog (global directive) is the declarative form of
        # --syslog; the CLI flag wins
        if args.syslog or global_config.get("syslog"):
            engine.set_syslog(args.syslog or global_config.get("syslog"))
        for directory in _FQA_UNPACK_DIRS:
            # CLI-unpacked .fqa packages die with the engine
            engine.track_temp_dir(directory)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    await engine.start()
    ui_server: ApiServer | None = None
    ui_viewer_msg: str | None = None
    if args.ui is not None:
        # the UI viewer's channel: serve the sim API over HTTP (viewer polls
        # /devices and fires /plugins/callUIEvent — the HC3's own contract).
        # The server never counts as pending work; this task owns it.
        ui_server = ApiServer(engine.api, port=args.ui)
        try:
            await ui_server.start()
        except (OSError, RuntimeError) as exc:
            parser.error(f"cannot serve the UI API on port {args.ui}: {exc}")
        # logged after the greeting below, so the greeting always opens the
        # startup output (the pump prints messages in post order)
        ui_viewer_msg = (
            f"flua: UI viewer on http://127.0.0.1:{ui_server.port}/ — open it in a browser"
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
    main_qa_id: int | None = None
    for path, code, local_params in qa_specs:
        qa_config = dict(global_config)
        qa_config.update(local_params)
        arg0 = path if path is not None else "flua"
        try:
            qa_id = engine.start_qa(path, code, qa_config, arg0)
        except ValueError as exc:
            parser.error(str(exc))
        if main_qa_id is None:
            main_qa_id = qa_id
        if args.watch:
            info = engine.qa_info(qa_id)
            for f in info["files"] if info else []:
                if f.get("path"):
                    watch_paths.setdefault(f["path"], set()).add(qa_id)

    if not args.nogreet:
        # one line, posted AFTER the QAs are prepared: the mode (and the
        # proxy's HC3 id in proxy mode) is only known once the proxies are
        # resolved. It still rides the pump's FIFO ahead of the QAs' own
        # output — the QAs boot as 0 ms timers, delivered after this log.
        mode = "offline (sim HC3, real network)" if api_mode == "local" else "online"
        if main_qa_id is not None:
            info = engine.qa_info(main_qa_id)
            if info and info.get("proxy"):
                mode = f"proxy:{main_qa_id}"
        engine.post_log(
            "info",
            f"🚀 flua {__version__} ({engine.lua_version()}, "
            f"Python {sys.version.split()[0]}), mode {mode}",
        )
    if ui_viewer_msg is not None:
        engine.post_log("info", ui_viewer_msg)

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
                            engine.post_log(
                                "info", f"[watch] restarted QA {qa_id} ({Path(path).name})"
                            )

        asyncio.create_task(watch_loop(), name="flua-watch")

    start = time.monotonic()
    max_virtual_seconds = None if max_hours is None else max_hours * 3600.0
    # cap simulated time at the run limit (fixed --run-for, --%%maxhours) so
    # instant mode stops firing exactly there instead of overshooting
    horizon: float | None = max_virtual_seconds
    if args.run_for is not None and args.run_for < 0 and not step:
        # the fixed --run-for is a virtual-time cap; step mode advances
        # only by deadline jumps, so the cap would block the very timers
        # the user wants to step through — there the negative form means
        # "run until idle, at most N wall seconds" (the wall leash below)
        horizon = -args.run_for if horizon is None else min(horizon, -args.run_for)
    if horizon is not None:
        engine.limit_run(horizon)
    # the step-mode fixed-run idle exit requires a short streak of CONTINUOUS
    # idle: a rule that re-registers its next timer asynchronously (ER's
    # daily machinery hops through its event queue) briefly shows no pending
    # work between hops — sampling that gap made the exit code a coin flip
    # (73–342 next-day re-fires before exit 0). Three idle polls (~150 ms)
    # make the decision deterministic: a truly re-arming engine re-establishes
    # work within the window and rides the wall cap (exit 1); a drained run
    # exits 0 after the streak.
    settle_idle = (
        args.run_for is not None and args.run_for < 0 and engine.clock.step
    )
    try:
        idle_streak = 0
        while True:
            if not _keep_running(
                engine, args.run_for, start, max_virtual_seconds, ui_server is not None
            ):
                break
            if settle_idle and not engine.has_pending_work():
                idle_streak += 1
                if idle_streak >= 3:
                    break
            else:
                idle_streak = 0
            await asyncio.sleep(0.05)
        # --run-for's wall deadline cut the run short with work still
        # pending: a hung/incomplete suite must not look green — exit 1
        # with a named reason (checked before stop(): the timers/queues
        # that count as pending work still exist)
        # --run-for's wall deadline cut the run short with work still
        # pending: a hung/incomplete suite must not look green — exit 1
        # with a named reason (checked before stop(): the timers/queues
        # that count as pending work still exist). The negative form's
        # wall cap is the same leash in step mode (the run ends at the
        # cap only when the timer chain never drained).
        wall = time.monotonic() - start
        if args.run_for is not None and args.run_for > 0:
            wall_capped = wall >= args.run_for
        elif args.run_for is not None and args.run_for < 0 and engine.clock.step:
            wall_capped = wall >= -args.run_for
        else:
            wall_capped = False
        expired = wall_capped and engine.has_pending_work()
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            await engine.stop()
        if ui_server is not None:
            await ui_server.stop()
    if expired:
        message = f"--run-for {args.run_for}s wall cap reached with work pending"
        engine.post_log("warning", "flua: " + message)
        print(f"flua: {message} (exit 1)", file=sys.stderr)
        return 1
    if max_virtual_seconds is not None and engine.clock.elapsed() >= max_virtual_seconds:
        print(f"flua: virtual time limit reached ({max_hours}h)", file=sys.stderr)
    for qa_id, name, code in engine.failed_qas():
        # the final verdict: agents read stderr to attribute a bare exit code
        print(f"flua: QA {name} ({qa_id}) exited with code {code}", file=sys.stderr)
    return engine.exit_code


def _check_cli(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Static checks for every QA file / -e code; exit 1 only on errors."""
    from .check import check_file, check_source

    engine = LuaEngine()
    lua = engine.lua_runtime()
    findings: list[str] = []
    unpack_dirs: list[str] = []
    if args.code is not None:
        findings += check_source(args.code, "<command line>", lua)
    for script in args.scripts:
        path = Path(script)
        if not path.exists():
            parser.error(f"cannot open {script}: no such file")
        if path.suffix.lower() == ".fqa":
            main_path, _fqa = _unpack_fqa_script(parser, path)
            path = Path(main_path)
            unpack_dirs = list(_FQA_UNPACK_DIRS)
        findings += check_file(str(path.resolve()), lua)
    # check mode never starts the engine: clean the unpack dirs here
    for directory in unpack_dirs:
        with contextlib.suppress(OSError):
            shutil.rmtree(directory, ignore_errors=True)
    if args.json:
        parsed = []
        for line in findings:
            file, _, rest = line.partition(": ")
            severity, _, message = rest.partition(": ")
            parsed.append({"file": file, "severity": severity, "message": message})
        payload = {"ok": not any(f["severity"] == "error" for f in parsed), "findings": parsed}
        print(json.dumps(payload))
        return 0 if payload["ok"] else 1
    if not findings:
        print("ok")
        return 0
    for line in findings:
        print(line)
    return 1 if any(": error:" in line for line in findings) else 0


def _export_cli(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """flua export script.lua -o out.fqa — the deploy artifact, without running."""
    path = Path(args.script)
    try:
        source = path.read_text(encoding="utf-8")
        annotations = expand_includes(
            parse_annotations(source, warn_unknown=False), path.parent
        )
    except OSError as exc:
        parser.error(f"cannot open {args.script}: {exc}")
    except ValueError as exc:
        parser.error(f"error in {args.script}: {exc}")
    try:
        fqa, _ = build_fqa(args.script, dist=True)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    output = Path(args.output) if args.output else default_fqa_output(path, annotations)
    output.write_text(json.dumps(fqa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
    """Let ``--debugger script.lua`` / ``--ui script.lua`` mean the
    default ports (8172 / 8090).

    Both flags take an optional port, but argparse's optional-value
    arguments only use their default when the next token looks like an
    option — so ``flua --debugger script.lua`` would parse the script as
    the port and fail with "invalid int value" (same for --ui). When either
    flag is followed by a non-option, non-integer token, move the bare flag
    to the end so the script stays a positional and the flag takes its
    const. An explicit ``--debugger PORT script.lua`` (or ``--debugger=PORT``)
    is untouched.
    """
    out: list[str] = []
    moved: list[str] = []
    i = 0
    while i < len(argv):
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if (
            argv[i] in ("--debugger", "--ui")
            and nxt is not None
            and not nxt.startswith("-")
            and not nxt.isdigit()
        ):
            moved.append(argv[i])
        else:
            out.append(argv[i])
        i += 1
    return out + moved


def _examples_dir() -> Path:
    """The installed examples directory: the wheel ships examples/ as the
    flua.examples package; an editable install or checkout resolves to the
    repo's own examples/."""
    try:
        import flua.examples as examples_pkg

        location = getattr(examples_pkg, "__file__", None)
        if location:
            return Path(location).resolve().parent
    except ImportError:
        pass
    return Path(__file__).resolve().parent.parent.parent / "examples"


def main(argv: list[str] | None = None) -> int:
    # Debug adapters capture pipes, whose Windows default encoding is not UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    raw = sys.argv[1:] if argv is None else argv
    # Tool commands get their own parsers — argparse subparsers would swallow
    # the run mode's first positional script. --tool/-t (downloadQA, uploadQA,
    # updateQA) is scanned before anything else, so it can sit anywhere.
    tool, rest = _find_tool(raw)
    if tool is not None:
        return _hc3_tool_main(tool, rest)
    if raw and raw[0] in ("export", "unpack", "test", "doctor", "record", "audit"):
        return _tool_main(raw)
    parser = _build_parser()
    args = parser.parse_args(_normalize_debugger_argv(raw))
    if args.version:
        if args.machine:
            # one JSON line: a stable capability probe (agents, installers,
            # the future MCP layer) — no prose to parse
            engine = LuaEngine()
            print(
                json.dumps(
                    {
                        "version": __version__,
                        "lua": engine.lua_version(),
                        "python": sys.version.split()[0],
                    }
                )
            )
        else:
            print(f"flua {__version__}")
        return 0
    if args.examples:
        print(_examples_dir())
        return 0
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # -v shows the exact invocation (argv + debugger env) — the quickest way
    # to see what a host like VS Code passes flua (launch configs, injected
    # mobdebug bootstraps, MOBDEBUG_PORT)
    logging.debug("argv: %s", sys.argv)
    logging.debug(
        "env: MOBDEBUG_PORT=%s",
        os.environ.get("MOBDEBUG_PORT"),
    )
    try:
        return asyncio.run(_run(parser, args))
    except KeyboardInterrupt:
        print("flua: interrupted", file=sys.stderr)
        return 130


def _tool_parser(command: str) -> argparse.ArgumentParser:
    if command == "audit":
        parser = argparse.ArgumentParser(
            prog="flua audit",
            description="Coverage of the HC3 surface the sim implements: "
            "REST routes and the device catalog.",
        )
        _audit_add_arguments(parser)
        return parser
    if command == "record":
        parser = argparse.ArgumentParser(
            prog="flua record",
            description="Record a real house session: snapshot the HC3's devices "
            "and capture its refreshState events into a replayable JSON file.",
        )
        _record_add_arguments(parser)
        return parser
    if command == "doctor":
        parser = argparse.ArgumentParser(
            prog="flua doctor",
            description="Health-check a flua workspace: runtime, virtualenv, "
            "HC3 credentials/reachability, LuaLS and VS Code setup, the "
            "marketplace extension, and flua-mcp.",
        )
        _doctor_add_arguments(parser)
        return parser
    if command == "test":
        parser = argparse.ArgumentParser(
            prog="flua test",
            description="Run self-asserting test QAs (*_test.lua, the "
            "quickapp-test pattern) and report PASS/FAIL/TIMEOUT.",
        )
        _test_add_arguments(parser)
        return parser
    if command == "export":
        parser = argparse.ArgumentParser(
            prog="flua export", description="Export a QA file as a .fqa package."
        )
        parser.add_argument("script", help="the QA main file")
        parser.add_argument(
            "-o",
            "--output",
            metavar="FILE",
            help="output .fqa path (default: <QA name>.fqa — the --%%name, "
            "or MyQA.fqa without one — next to the script)",
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
    if command == "test":
        return _test_run(tool, args)
    if command == "doctor":
        return _doctor_run(tool, args)
    if command == "record":
        return _record_run(tool, args)
    if command == "audit":
        return _audit_run(tool, args)
    return _unpack_cli(tool, args)


# -- --tool/-t: HC3 file transfer tools -----------------------------------------


def _find_tool(raw: list[str]) -> tuple[str | None, list[str]]:
    """Extract --tool NAME / -t NAME / --tool=NAME / -tNAME from argv; the
    remaining arguments continue to the tool's own parser. A bare --tool/-t
    (no name) returns "", which lists the installed tools."""
    for i, arg in enumerate(raw):
        if arg in ("--tool", "-t"):
            if i + 1 >= len(raw):
                return "", raw[:i] + raw[i + 1 :]
            return raw[i + 1], raw[:i] + raw[i + 2 :]
        for prefix in ("--tool=", "-t"):
            if arg.startswith(prefix) and len(arg) > len(prefix):
                return arg[len(prefix) :], raw[:i] + raw[i + 1 :]
    return None, raw


def _hc3_tool_main(name: str, rest: list[str]) -> int:
    """Dispatch a --tool command: the tools package builds the parser from
    the tool's own module (one file per tool, auto-discovered)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return run_tool(name, rest)


if __name__ == "__main__":
    sys.exit(main())
