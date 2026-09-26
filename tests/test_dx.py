"""Phase-1 developer tools: --check, export/unpack, --watch, the house seed."""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FLOA = [sys.executable, "-m", "flua"]


def _run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*FLOA, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# -- --check ------------------------------------------------------------------


def test_check_clean_file() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "good.lua"
        script.write_text("--%%name:x\nprint('hi')\n")
        result = _run("--check", str(script))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ok" in result.stdout


def test_check_flags_unknown_directive() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "typo.lua"
        script.write_text("--%%instnat:true\nprint('hi')\n")  # typo: instant
        result = _run("--check", str(script))
        assert result.returncode == 0  # warnings don't fail the check
        assert "unknown directive --%%instnat" in result.stdout


def test_check_flags_deprecated_api() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "dep.lua"
        script.write_text("api.get('/quickApp/export/5000')\n")
        result = _run("--check", str(script))
        assert result.returncode == 0
        assert "deprecated API: GET /quickApp/export/5000" in result.stdout


def test_check_syntax_error_exits_1() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "syntax.lua"
        script.write_text("print(\n")
        result = _run("--check", str(script))
        assert result.returncode == 1
        assert "error: syntax" in result.stdout


# -- export / unpack ------------------------------------------------------------


def test_export_and_unpack_roundtrip(tmp_path) -> None:
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%name:packaged\n"
        "--%%file:lib.lua,lib\n"
        "-- --------------- EOH ---------------\n"
        "print('RUNS', LIB)\n"
    )
    (tmp_path / "lib.lua").write_text("LIB = 'ok'\n")
    package = tmp_path / "out.fqa"
    result = _run("export", str(main), "-o", str(package))
    assert result.returncode == 0, result.stdout + result.stderr
    fqa = json.loads(package.read_text())
    assert fqa["name"] == "packaged"
    assert fqa["type"] == "com.fibaro.binarySwitch"
    assert [f["name"] for f in fqa["files"]] == ["main", "lib"]

    target = tmp_path / "project"
    result = _run("unpack", str(package), "-d", str(target))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / "main.lua").exists()
    assert (target / "lib").exists()
    header = (target / "main.lua").read_text()
    assert "--%%name:packaged" in header
    assert "--%%file:lib,lib" in header
    assert "EOH" in header
    assert "print('RUNS', LIB)" in header  # main content follows the header

    # the unpacked project runs as a normal flua project
    result = _run("--api", "local", str(target / "main.lua"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUNS ok" in result.stdout


# -- --watch ----------------------------------------------------------------------


def _collect(proc: subprocess.Popen) -> list[str]:
    lines: list[str] = []
    threading.Thread(
        target=lambda: [lines.append(line) for line in proc.stdout], daemon=True
    ).start()
    return lines


def _wait_for(lines: list[str], marker: str, timeout: float) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        text = "".join(lines)
        if marker in text:
            return text
        time.sleep(0.05)
    raise AssertionError(f"{marker!r} not seen in output:\n{''.join(lines)}")


def test_watch_restarts_on_change(tmp_path) -> None:
    main = tmp_path / "main.lua"
    main.write_text("setTimeout(function() print('REV 1') end, 20)\n")
    proc = subprocess.Popen(
        [*FLOA, "--api", "local", "--watch", str(main)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        lines = _collect(proc)
        _wait_for(lines, "REV 1", 10)
        main.write_text("setTimeout(function() print('REV 2') end, 20)\n")
        text = _wait_for(lines, "REV 2", 10)
        assert "[watch] restarted QA 5000" in text
    finally:
        proc.terminate()
        proc.wait(timeout=5)


# -- the house seed -----------------------------------------------------------------


def test_house_seed_runs(tmp_path) -> None:
    script = tmp_path / "house.lua"
    script.write_text(
        "setTimeout(function()\n"
        "  print('ROOM1', #api.get('/devices?roomID=1'))\n"
        "  print('NIGHT', fibaro.getGlobalVariable('nightMode'))\n"
        "  print('SCENES', #api.get('/scenes'))\n"
        "end, 20)\n"
    )
    result = _run("--api", "local", "--seed", "examples/house.json", str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ROOM1 2" in result.stdout
    assert "NIGHT false" in result.stdout
    assert "SCENES 1" in result.stdout


# -- virtual start time --------------------------------------------------------


def test_start_time_crosses_new_year_instantly(tmp_path) -> None:
    # --%%time:start=... + instant: the 20 s timer fires past midnight —
    # the QA observes the year roll over without waiting
    script = tmp_path / "ny.lua"
    script.write_text(
        "--%%time:start=2027/12/31 23:59:50,instant=true\n"
        "-- --------------- EOH ---------------\n"
        "print('T0', os.date('%Y/%m/%d %H:%M:%S'))\n"
        "setTimeout(function() print('T1', os.date('%Y/%m/%d %H:%M:%S')) end, 20000)\n"
    )
    result = _run("--api", "local", str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "T0 2027/12/31 23:59:50" in result.stdout
    assert "T1 2028/01/01 00:00:10" in result.stdout


def test_start_time_bare_form(tmp_path) -> None:
    # the bare --%%time:<when> form sets the start time directly
    script = tmp_path / "bare.lua"
    script.write_text(
        "--%%time:2027/10/6 12:00:20\n"
        "-- --------------- EOH ---------------\n"
        "print('WHEN', os.date('%Y/%m/%d %H:%M:%S'))\n"
    )
    result = _run("--api", "local", str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WHEN 2027/10/06 12:00:20" in result.stdout


def test_start_flag_wins_over_directive(tmp_path) -> None:
    script = tmp_path / "flag.lua"
    script.write_text(
        "--%%time:start=2020/1/1 00:00:00\n"
        "-- --------------- EOH ---------------\n"
        "print('WHEN', os.date('%Y/%m/%d %H:%M:%S'))\n"
    )
    result = _run("--api", "local", "--start", "2027/10/6 12:00:20", str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WHEN 2027/10/06 12:00:20" in result.stdout
    assert "WHEN 2020/1/1" not in result.stdout


def test_start_bad_format_is_an_error(tmp_path) -> None:
    script = tmp_path / "ok.lua"
    script.write_text("print('x')\n")
    result = _run("--start", "garbage", str(script))
    assert result.returncode == 2
    assert "cannot parse start time" in result.stderr


# -- the os.getenv chain --------------------------------------------------------


def test_getenv_reads_local_dotenv(tmp_path) -> None:
    # a .env in the working directory feeds os.getenv in QA code
    (tmp_path / ".env").write_text("# dev secrets\nAPI_TOKEN=secret123\n")
    script = tmp_path / "env.lua"
    script.write_text(
        "print('TOKEN', os.getenv('API_TOKEN'))\nprint('MISSING', os.getenv('NOPE'))\n"
    )
    result = subprocess.run(
        [*FLOA, "--api", "local", str(script)],
        cwd=tmp_path,  # the local .env lives here
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TOKEN secret123" in result.stdout
    assert "MISSING" in result.stdout  # nil is fine, printed as nothing


def test_getenv_falls_back_to_process_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FROM_PROCESS", "from-shell")
    script = tmp_path / "env.lua"
    script.write_text("print('PROC', os.getenv('FROM_PROCESS'))\n")
    result = subprocess.run(
        [*FLOA, "--api", "local", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROC from-shell" in result.stdout


# -- .directives defaults -------------------------------------------------------


def test_directives_file_supplies_main_qa_defaults(tmp_path) -> None:
    # a .directives file in the working directory is read as defaults for the
    # MAIN QA: the engine follows its mode (offline here) and the QA sees
    # the default name
    (tmp_path / ".directives").write_text("--%%name:Default\n--%%mode:offline\n")
    script = tmp_path / "main.lua"
    script.write_text("print('NAME', _FLUA.config.name)\n")
    result = subprocess.run(
        [*FLOA, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mode offline" in result.stdout  # the file's mode picked the sim
    assert "NAME Default" in result.stdout


def test_directives_file_qa_overrides_defaults(tmp_path) -> None:
    # the QA's own directives override the file's; the mode family overrides
    # as a whole, so an explicit opt-out beats the file's offline default
    (tmp_path / ".directives").write_text("--%%mode:offline\n")
    script = tmp_path / "main.lua"
    script.write_text("--%%name:Mine\n--%%offline:false\nprint('RAN')\n")
    result = subprocess.run(
        [*FLOA, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # opting out of the file's offline default -> online, which needs HC3
    # credentials — the loud error proves the override took effect
    assert result.returncode == 2
    assert "HC3_URL" in result.stderr


def test_directives_file_applies_to_main_qa_only(tmp_path) -> None:
    # secondary QAs do not inherit the file's defaults
    (tmp_path / ".directives").write_text("--%%name:Default\n--%%mode:offline\n")
    a = tmp_path / "a.lua"
    a.write_text("print('A', _FLUA.config.name)\n")
    b = tmp_path / "b.lua"
    b.write_text("print('B', _FLUA.config.name)\n")
    result = subprocess.run(
        [*FLOA, str(a), str(b)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "A Default" in result.stdout  # the main QA got the file's name
    assert "B b" in result.stdout  # the secondary QA kept its own name


# -- debug directives ------------------------------------------------------------


def test_debug_directive_logs_events_and_api_calls(tmp_path) -> None:
    # --%%debug:refreshState logs events in a short form (cut at
    # --%%loglength), --%%debug:api logs the QA's api.* calls
    script = tmp_path / "dbg.lua"
    script.write_text(
        "--%%debug:refreshState=true,api=true\n"
        "--%%loglength:90\n"
        "-- --------------- EOH ---------------\n"
        "function QuickApp:onInit()\n"
        "  self:updateProperty('value', 'a-very-long-property-value-to-force-a-cut')\n"
        "  local _, s = api.get('/devices/' .. self.id)\n"
        "  print('DONE', s)\n"
        "end\n"
    )
    result = subprocess.run(
        [*FLOA, "--api", "local", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # the refreshStates event, in the short form with the data fields
    assert "refreshState DevicePropertyUpdatedEvent" in result.stdout
    assert "property=value" in result.stdout
    assert "newValue=a-very-long" in result.stdout  # the value made it in
    assert "..." in result.stdout  # ... and the line was cut at 90 chars
    # the api call
    assert "api GET /devices/5000" in result.stdout
    assert "DONE 200" in result.stdout


# -- os.time integrity ---------------------------------------------------------


def test_os_time_returns_whole_seconds(tmp_path) -> None:
    # Lua's os.time() returns integer seconds — never the clock's fractions
    script = tmp_path / "t.lua"
    script.write_text(
        "print('INT', os.time() % 1 == 0, type(os.time()))\n"
        "setTimeout(function() print('INT2', os.time() % 1 == 0) end, 20)\n"
    )
    result = _run("--api", "local", str(script))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INT true number" in result.stdout
    assert "INT2 true" in result.stdout
