"""Phase-1 developer tools: --check, export/unpack, --watch, the house seed."""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

FLOA = [sys.executable, "-m", "flua"]


def _run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*FLOA, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


@pytest.mark.parametrize("initial_encoding", ["cp1252", "utf-8"])
def test_cli_uses_utf8_output(initial_encoding) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from flua.cli import main; "
            "code = main(['--api', 'local', '--color', 'never', '-e', "
            "\"print('\\U0001f680 QA'); exit(0)\"]); "
            "print('\\U0001f680 stderr', file=sys.stderr); sys.exit(code)",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONIOENCODING": initial_encoding},
        capture_output=True,
        timeout=30,
    )
    stdout = result.stdout.decode("utf-8")
    stderr = result.stderr.decode("utf-8")
    assert result.returncode == 0, stdout + stderr
    assert "\U0001f680 flua" in stdout
    assert "\U0001f680 QA" in stdout
    assert stderr.strip() == "\U0001f680 stderr"
    assert "\\U0001f680" not in stdout


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


def test_check_var_with_package_value_is_clean() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "pkg.lua"
        script.write_text('--%%var:pwd=config.pwd,"<set me>"\nprint("hi")\n')
        result = _run("--check", str(script))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "unknown directive" not in result.stdout  # varPkg is internal


def test_check_flags_var_svar_conflict() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "both.lua"
        script.write_text("--%%var:x=1\n--%%svar:x=2\nprint('hi')\n")
        result = _run("--check", str(script))
        assert result.returncode == 0  # a warning, not an error
        assert "both --%%var and --%%svar declare 'x'" in result.stdout


def test_check_legacy_file_colon_form_hints() -> None:
    # --%%file:path:name is the legacy plua spelling — the error must say so,
    # not just show a doubled path
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "legacy.lua"
        script.write_text("--%%file:lib.lua:Lib\n")
        result = _run("--check", str(script))
        assert result.returncode == 1  # missing files are error findings
        assert "legacy --%%file:path:name spelling" in result.stdout


def test_check_flags_deprecated_api() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "dep.lua"
        script.write_text("api.get('/quickApp/export/5000')\n")
        result = _run("--check", str(script))
        assert result.returncode == 0
        assert "deprecated API: GET /quickApp/export/5000" in result.stdout


def test_version_machine_json() -> None:
    # --version --machine: one JSON line agents/installers can probe
    result = _run("--version", "--machine")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["version"].count(".") >= 2
    assert payload["integerBytes"] == 8  # native Lua integer width (HC3: 8)
    assert isinstance(payload["locale"], str) and payload["locale"]
    assert payload["lupa"] and payload["lua"].startswith("Lua")
    assert payload["lua"].startswith("Lua 5")
    assert payload["python"].count(".") == 2
    # the plain form stays human text
    result = _run("--version")
    assert result.returncode == 0
    assert result.stdout.strip().startswith("flua ")


def test_check_json_output() -> None:
    # --check --json: structured findings instead of prose lines
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        good = Path(d) / "good.lua"
        good.write_text("--%%name:x\nprint('hi')\n")
        result = _run("--check", "--json", str(good))
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload == {"ok": True, "findings": []}
        bad = Path(d) / "bad.lua"
        bad.write_text("print(\n")
        result = _run("--check", "--json", str(bad))
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["findings"][0]["severity"] == "error"
        assert "syntax" in payload["findings"][0]["message"]
        assert payload["findings"][0]["file"] == str(bad.resolve())


def test_check_follows_file_includes() -> None:
    # --check validates the whole project: the main file plus every
    # --%%file include, each with its own file context
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        main = Path(d) / "main.lua"
        lib = Path(d) / "lib.lua"
        main.write_text("--%%name:proj\n--%%file:lib.lua,lib\nprint(LIB)\n")
        lib.write_text("LIB = 'ok'\n")
        result = _run("--check", str(main))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ok" in result.stdout
        # a syntax error in the include is caught and named
        lib.write_text("LIB = )\n")
        result = _run("--check", str(main))
        assert result.returncode == 1
        assert str(lib) in result.stdout
        assert "error: syntax" in result.stdout
        # a missing include is an error, like the runtime's load
        lib.unlink()
        result = _run("--check", str(main))
        assert result.returncode == 1
        assert "no such file" in result.stdout


def test_check_syntax_error_exits_1() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "syntax.lua"
        script.write_text("print(\n")
        result = _run("--check", str(script))
        assert result.returncode == 1
        assert "error: syntax" in result.stdout


# -- --examples -----------------------------------------------------------------


def test_examples_flag_prints_installed_examples_dir() -> None:
    # pip users get the examples through the wheel (flua.examples package
    # data); --examples tells them where they are installed
    result = _run("--examples")
    assert result.returncode == 0, result.stdout + result.stderr
    directory = Path(result.stdout.strip())
    assert directory.name == "examples"
    assert (directory / "timers.lua").is_file()
    assert (directory / "house.json").is_file()


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
    assert (target / "packaged_main.lua").exists()  # <QA-name>_main.lua
    assert (target / "packaged_lib.lua").exists()  # extras: <QA-name>_<file>.lua
    header = (target / "packaged_main.lua").read_text()
    assert "--%%name:packaged" in header
    assert "--%%file:packaged_lib.lua,lib" in header
    assert "EOH" in header
    assert "print('RUNS', LIB)" in header  # main content follows the header

    # the unpacked project runs as a normal flua project
    result = _run("--api", "local", str(target / "packaged_main.lua"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUNS ok" in result.stdout


def test_fqa_as_script_runs_the_packaged_qa(tmp_path) -> None:
    # flua <file>.fqa: the CLI unpacks the package to a temp dir and runs
    # its main — downloaded/packed fqas are directly runnable
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%name:fqarun\n"
        "--%%file:lib.lua,lib\n"
        "-- --------------- EOH ---------------\n"
        "print('RUNS', LIB)\n"
    )
    (tmp_path / "lib.lua").write_text("LIB = 'ok'\n")
    package = tmp_path / "runme.fqa"
    result = _run("export", str(main), "-o", str(package))
    assert result.returncode == 0, result.stdout + result.stderr
    result = _run("--api", "local", str(package))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUNS ok" in result.stdout


def test_fqa_as_script_applies_initial_interfaces(tmp_path) -> None:
    # a packaged QA's initialInterfaces survive the CLI unpack: the engine
    # applies them to the device at load (like import_qa does for uploads)
    main = tmp_path / "main.lua"
    main.write_text(
        "--%%name:ifaces\n"
        "print('IFACES', table.concat(api.get('/devices/'.._FLUA.qaId).interfaces, ','))\n"
        "exit(0)\n"
    )
    package = tmp_path / "ifaces.fqa"
    result = _run("export", str(main), "-o", str(package))
    assert result.returncode == 0, result.stdout + result.stderr
    fqa = json.loads(package.read_text())
    fqa["initialInterfaces"] = ["light", "quickApp"]
    package.write_text(json.dumps(fqa))
    result = _run("--api", "local", str(package))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "light" in result.stdout  # quickApp is skipped (the skeleton has it)


def test_fqa_as_script_check(tmp_path) -> None:
    # flua --check <file>.fqa checks the unpacked package
    main = tmp_path / "main.lua"
    main.write_text("--%%name:checkme\nprint('x')\n")
    package = tmp_path / "checkme.fqa"
    result = _run("export", str(main), "-o", str(package))
    assert result.returncode == 0, result.stdout + result.stderr
    result = _run("--check", str(package))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_fqa_as_script_bad_package_errors(tmp_path) -> None:
    # invalid JSON and shape-less JSON both fail with a clean message
    garbage = tmp_path / "bad.fqa"
    garbage.write_text("{not json")
    result = _run("--api", "local", str(garbage))
    assert result.returncode != 0
    assert "cannot open" in result.stderr
    wrong_shape = tmp_path / "wrong.fqa"
    wrong_shape.write_text('{"name": "nofiles"}')
    result = _run("--api", "local", str(wrong_shape))
    assert result.returncode != 0
    assert "not a .fqa package" in result.stderr


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


# -- include directives --------------------------------------------------------


def test_include_directive_supplies_defaults(tmp_path) -> None:
    # --%%include:<file> inserts the file's directives as defaults: the
    # engine follows the included mode (offline here) and the QA sees the
    # included name; the QA's own directives override them
    (tmp_path / "defaults.lua").write_text("--%%name:Default\n--%%mode:offline\n")
    script = tmp_path / "main.lua"
    script.write_text("--%%include:defaults.lua\nprint('NAME', _FLUA.config.name)\n")
    result = subprocess.run(
        [*FLOA, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mode offline" in result.stdout  # the included mode picked the sim
    assert "NAME Default" in result.stdout


def test_include_directive_qa_overrides_defaults(tmp_path) -> None:
    # the QA's own directives override the included file's; the mode family
    # overrides as a whole, so an explicit opt-out beats the included mode
    (tmp_path / "defaults.lua").write_text("--%%mode:offline\n")
    script = tmp_path / "main.lua"
    script.write_text("--%%include:defaults.lua\n--%%name:Mine\n--%%offline:false\nprint('RAN')\n")
    result = subprocess.run(
        [*FLOA, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # opting out of the included offline default -> online, which needs HC3
    # credentials — the loud error proves the override took effect
    assert result.returncode == 2
    assert "HC3_URL" in result.stderr


def test_include_directive_applies_to_each_qa_that_includes(tmp_path) -> None:
    # every QA resolves its own include — a QA without one stays untouched
    (tmp_path / "defaults.lua").write_text("--%%name:Default\n--%%mode:offline\n")
    a = tmp_path / "a.lua"
    a.write_text("--%%include:defaults.lua\nprint('A', _FLUA.config.name)\n")
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
    assert "A Default" in result.stdout  # the including QA got the defaults
    assert "B b" in result.stdout  # the other QA kept its own name


def test_include_directive_missing_file_errors(tmp_path) -> None:
    # an explicit include that cannot be read is a loud error, not silence
    script = tmp_path / "main.lua"
    script.write_text("--%%include:missing.lua\nprint('RAN')\n")
    result = subprocess.run(
        [*FLOA, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "cannot read" in result.stderr


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


class _StrictHttpHandler(BaseHTTPRequestHandler):
    """One 200 response for the strict-tests net-callback fixture."""

    def do_GET(self):
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def strict_http_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StrictHttpHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


def _sticky_qa(tmp_path: Path) -> Path:
    script = tmp_path / "sticky.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  setTimeout(function() error('EXPECTED_CALLBACK_FAILURE') end, 10)\n"
        "  setTimeout(function() print('LATER OK'); _FLUA.exit(0) end, 50)\n"
        "end\n"
    )
    return script


def test_strict_tests_sticky_callback_failure(tmp_path) -> None:
    # the forum's P0 acceptance: a timer assertion fails, a later callback
    # prints success and exits 0 — the final status is still failure. The
    # flag is opt-in: without it the legacy exit-0 behavior holds, and a
    # CAUGHT expected error still passes.
    script = _sticky_qa(tmp_path)
    strict = _run("--api", "local", "--color", "never", "--strict-tests", str(script))
    assert strict.returncode == 1, strict.stdout + strict.stderr
    assert "LATER OK" in strict.stdout  # the later callback DID run and exit 0
    legacy = _run("--api", "local", "--color", "never", str(script))
    assert legacy.returncode == 0  # legacy mode unchanged
    # the --%%strict-tests directive is the declarative spelling
    directive = _run(
        "--api", "local", "--color", "never", "-D", "strict-tests:true", str(script)
    )
    assert directive.returncode == 1
    # an error the QA code catches itself is not an unhandled callback error
    caught = tmp_path / "caught.lua"
    caught.write_text(
        "function QuickApp:onInit()\n"
        "  setTimeout(function()\n"
        "    local ok = pcall(function() error('EXPECTED') end)\n"
        "    print('CAUGHT', ok)\n"
        "    _FLUA.exit(0)\n"
        "  end, 10)\n"
        "end\n"
    )
    result = _run("--api", "local", "--color", "never", "--strict-tests", str(caught))
    assert result.returncode == 0, result.stdout + result.stderr


def test_strict_tests_covers_ui_callbacks(tmp_path) -> None:
    script = tmp_path / "ui.lua"
    script.write_text(
        "--%%u:{button='B1',text='Press me',onReleased='go'}\n"
        "function QuickApp:UIAction(el, ev, v) error('UI_BOOM') end\n"
        "function QuickApp:onInit()\n"
        "  setTimeout(function()\n"
        "    _FLUA.uiEvent('B1', 'onReleased')\n"
        "    setTimeout(function() _FLUA.exit(0) end, 100)\n"
        "  end, 20)\n"
        "end\n"
    )
    result = _run(
        "--api",
        "local",
        "--color",
        "never",
        "--strict-tests",
        "--result-json",
        str(tmp_path / "r.json"),
        str(script),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    record = json.loads((tmp_path / "r.json").read_text())
    assert record["status"] == "failed" and record["exitCode"] == 1
    kinds = [f["callbackKind"] for f in record["failures"]]
    assert "ui" in kinds


def test_strict_tests_covers_net_callbacks(tmp_path, strict_http_server) -> None:
    script = tmp_path / "net.lua"
    script.write_text(
        "function QuickApp:onInit()\n"
        "  local cl = net.HTTPClient({timeout=2000})\n"
        "  cl:request("
        + repr(strict_http_server)
        + ", {\n"
        "    success = function() error('NET_BOOM') end,\n"
        "    error = function() _FLUA.exit(0) end,\n"
        "  })\n"
        "  setTimeout(function() _FLUA.exit(0) end, 3000)\n"
        "end\n"
    )
    result = _run(
        "--api",
        "local",
        "--color",
        "never",
        "--strict-tests",
        "--result-json",
        str(tmp_path / "r.json"),
        str(script),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    record = json.loads((tmp_path / "r.json").read_text())
    kinds = [f["callbackKind"] for f in record["failures"]]
    assert "net" in kinds


def test_result_json_statuses(tmp_path) -> None:
    # passed: a clean instant run; timeout: the wall cap cut a pending run
    clean = tmp_path / "clean.lua"
    clean.write_text(
        "setTimeout(function() _FLUA.exit(0) end, 1000)\n"
    )
    passed = _run(
        "--api",
        "local",
        "--color",
        "never",
        "--instant",
        "--run-for",
        "-2",
        "--result-json",
        str(tmp_path / "clean.json"),
        str(clean),
    )
    assert passed.returncode == 0
    record = json.loads((tmp_path / "clean.json").read_text())
    assert record["schemaVersion"] == 1
    assert record["status"] == "passed" and record["exitCode"] == 0
    assert record["clockMode"] == "instant"
    assert record["virtualSeconds"] == 1.0
    assert record["cleanupComplete"] is True
    assert record["failures"] == []
    hang = tmp_path / "hang.lua"
    hang.write_text("setInterval(function() end, 1000)\n")
    timed_out = _run(
        "--api",
        "local",
        "--color",
        "never",
        "--run-for",
        "1",
        "--result-json",
        str(tmp_path / "hang.json"),
        str(hang),
    )
    assert timed_out.returncode == 1
    record = json.loads((tmp_path / "hang.json").read_text())
    assert record["status"] == "timeout" and record["exitCode"] == 1
    # atomic write: no .tmp litter after completion
    assert not (tmp_path / "hang.json.tmp").exists()


def test_capabilities_json_table() -> None:
    # --capabilities-json: the compatibility surface table agents/porters
    # probe. Unsupported/partial entries must be stated, never omitted —
    # the forum feedback's demand.
    result = _run("--capabilities-json")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == 1
    assert payload["runtime"]["version"].count(".") >= 2
    caps = payload["capabilities"]
    by_name = {
        entry["name"]: entry
        for category in caps.values()
        for entry in category
    }
    assert by_name["removeChildDevice"]["status"] == "implemented"
    assert by_name["simulated HC3 REST"]["status"] == "partial"  # shape-only stubs exist
    assert by_name["numeric32 emulation"]["status"] == "unsupported"
    assert by_name["--strict-tests / --result-json"]["status"] == "implemented"


def test_strict_tests_covers_mapped_ui_callbacks(tmp_path) -> None:
    # the pt Batch-B verification finding: a MAPPED button callback's error
    # is caught by the framework's callAction xpcall (onUIEvent -> timer ->
    # callAction), so the outer coroutine dispatch never saw it and strict
    # mode missed it. The framework catch boundary must record the failure.
    script = tmp_path / "mapped.lua"
    script.write_text(
        "--%%mode:offline\n"
        "--%%u:{button='btnFailure',text='Test',onReleased='failUi'}\n"
        "function QuickApp:failUi()\n"
        "  error('EXPECTED_UI_CALLBACK_FAILURE')\n"
        "end\n"
        "function QuickApp:onInit()\n"
        "  setTimeout(function()\n"
        "    _FLUA.uiEvent('btnFailure', 'onReleased')\n"
        "  end, 10)\n"
        "  setTimeout(function()\n"
        "    print('LATER OK')\n"
        "    _FLUA.exit(0)\n"
        "  end, 500)\n"
        "end\n"
    )
    result = _run(
        "--api",
        "local",
        "--strict-tests",
        "--result-json",
        str(tmp_path / "r.json"),
        "--run-for",
        "-2",
        str(script),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "LATER OK" in result.stdout
    record = json.loads((tmp_path / "r.json").read_text())
    assert record["status"] == "failed" and record["exitCode"] == 1
    failures = record["failures"]
    assert [f["callbackKind"] for f in failures] == ["ui"]
    # the ORIGINAL exception survives into the record (the pt finding: the
    # framework xpcall handler printed the error without returning it)
    assert len(failures) == 1
    assert "EXPECTED_UI_CALLBACK_FAILURE" in failures[0]["error"]
    # the equivalent direct self:UIAction spelling rides the same path
    direct = tmp_path / "direct.lua"
    direct.write_text(script.read_text().replace(
        "_FLUA.uiEvent('btnFailure', 'onReleased')",
        "self:UIAction('onReleased', 'btnFailure')",
    ))
    result = _run(
        "--api",
        "local",
        "--strict-tests",
        "--result-json",
        str(tmp_path / "d.json"),
        "--run-for",
        "-2",
        str(direct),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    record = json.loads((tmp_path / "d.json").read_text())
    assert [f["callbackKind"] for f in record["failures"]] == ["ui"]
