"""api.registerEndpoint: QA-registered emulated endpoints (offline sim).

The v1 contract: built-in routes always win; a QA's registered routes
answer ITS OWN api.* calls (pattern {params}, query separated, body
passed through); handlers run as QA callbacks on the pump (the full api
surface works — posting refreshState events included); a handler crash
completes the call with 500 instead of hanging; a handler calling its own
endpoint falls through to 404; routes die with the QA (exit/restart).
"""

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("lupa")

REPO_ROOT = Path(__file__).resolve().parent.parent

FLOA = [sys.executable, "-m", "flua"]


def _run_qa(code: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "qa.lua"
        path.write_text(code)
        return subprocess.run(
            [*FLOA, "--api", "local", "--color", "never", *args, str(path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )


def test_registered_endpoint_answers_get_with_params_and_query() -> None:
    result = _run_qa(
        "function QuickApp:onInit()\n"
        "  api.registerEndpoint('GET', '/panels/sprinklers/{id}', function(req)\n"
        "    return {name='Sprinklers ' .. req.params.id, q=req.query}, 200\n"
        "  end)\n"
        "  setTimeout(function()\n"
        "    local d, s = api.get('/panels/sprinklers/7?zone=2')\n"
        "    print('RESULT', s, json.encode(d))\n"
        "    exit(s == 200 and d.name == 'Sprinklers 7' and d.q.zone == '2' and 0 or 1)\n"
        "  end, 20)\n"
        "end\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"Sprinklers 7"' in result.stdout


def test_registered_endpoint_post_body_round_trip() -> None:
    result = _run_qa(
        "function QuickApp:onInit()\n"
        "  api.registerEndpoint('POST', '/vendor/custom', function(req)\n"
        "    return {echo=req.body}, 201\n"
        "  end)\n"
        "  setTimeout(function()\n"
        "    local d, s = api.post('/vendor/custom', {a=1, b='x'})\n"
        "    print('RESULT', s, json.encode(d))\n"
        "    exit(s == 201 and d.echo.a == 1 and d.echo.b == 'x' and 0 or 1)\n"
        "  end, 20)\n"
        "end\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_builtin_routes_win_over_registered() -> None:
    result = _run_qa(
        "function QuickApp:onInit()\n"
        "  api.registerEndpoint('GET', '/devices/{id}', function(req)\n"
        "    return {fake=true}, 200\n"
        "  end)\n"
        "  setTimeout(function()\n"
        "    local d, s = api.get('/devices/1')\n"
        "    print('RESULT', s, d and d.id, d and d.fake)\n"
        "    exit(s == 200 and d.id == 1 and d.fake == nil and 0 or 1)\n"
        "  end, 20)\n"
        "end\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 nil" in result.stdout  # the REAL device, not the fake


def test_handler_posts_refresh_state_events() -> None:
    result = _run_qa(
        "function QuickApp:onInit()\n"
        "  api.registerEndpoint('POST', '/vendor/event', function(req)\n"
        "    _FLUA.postRefreshEvent{type='DevicePropertyUpdatedEvent', "
        "      data={id=10, property='value', newValue=req.body.v}}\n"
        "    return nil, 204\n"
        "  end)\n"
        "  setTimeout(function()\n"
        "    api.post('/vendor/event', {v=true})\n"
        "    local feed, s = api.get('/refreshStates?last=0')\n"
        "    local found = false\n"
        "    for _, e in ipairs(feed.events or {}) do\n"
        "      if e.data and e.data.newValue == true then found = true end\n"
        "    end\n"
        "    print('EVENT', found)\n"
        "    exit(found and 0 or 1)\n"
        "  end, 20)\n"
        "end\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EVENT true" in result.stdout


def test_handler_crash_completes_with_500_not_a_hang() -> None:
    result = _run_qa(
        "function QuickApp:onInit()\n"
        "  api.registerEndpoint('GET', '/vendor/boom', function(req)\n"
        "    error('EXPECTED_HANDLER_CRASH')\n"
        "  end)\n"
        "  setTimeout(function()\n"
        "    local d, s = api.get('/vendor/boom')\n"
        "    print('RESULT', s)\n"
        "    exit(s == 500 and 0 or 1)  -- the QA continues after the crash\n"
        "  end, 20)\n"
        "end\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT 500" in result.stdout


def test_handler_calling_its_own_endpoint_gets_404() -> None:
    result = _run_qa(
        "function QuickApp:onInit()\n"
        "  api.registerEndpoint('GET', '/vendor/self', function(req)\n"
        "    local inner, s = api.get('/vendor/self')\n"
        "    return {inner=s}, 200\n"
        "  end)\n"
        "  setTimeout(function()\n"
        "    local d, s = api.get('/vendor/self')\n"
        "    print('RESULT', s, d and d.inner)\n"
        "    exit(s == 200 and d.inner == 404 and 0 or 1)\n"
        "  end, 20)\n"
        "end\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "200 404" in result.stdout


def test_routes_die_with_the_qa() -> None:
    result = _run_qa(
        "function QuickApp:onInit()\n"
        "  api.registerEndpoint('GET', '/vendor/gone', function(req)\n"
        "    return {alive=true}, 200\n"
        "  end)\n"
        "  setTimeout(function()\n"
        "    local d, s = api.get('/vendor/gone')\n"
        "    print('BEFORE', s)\n"
        "    exit(0)\n"
        "  end, 20)\n"
        "end\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BEFORE 200" in result.stdout
    # a fresh QA with no registration: the same path is a plain 404
    result = _run_qa(
        "setTimeout(function()\n"
        "  local d, s = api.get('/vendor/gone')\n"
        "  print('AFTER', s)\n"
        "  exit(s == 404 and 0 or 1)\n"
        "end, 20)\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "AFTER 404" in result.stdout


def test_module_registers_endpoints_for_its_qa() -> None:
    # the shareable-module model: a plain Lua module calls registerEndpoint
    # at require() time and the requiring QA's calls resolve through it
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        dir_ = Path(d)
        (dir_ / "panels.lua").write_text(
            "local M = {}\n"
            "api.registerEndpoint('GET', '/vendor/sprinklers', function(req)\n"
            "  return {count=3}, 200\n"
            "end)\n"
            "return M\n"
        )
        qa = dir_ / "qa.lua"
        qa.write_text(
            "function QuickApp:onInit()\n"
            "  require('panels')\n"
            "  setTimeout(function()\n"
            "    local d, s = api.get('/vendor/sprinklers')\n"
            "    print('RESULT', s, d and d.count)\n"
            "    exit(s == 200 and d.count == 3 and 0 or 1)\n"
            "  end, 20)\n"
            "end\n"
        )
        result = subprocess.run(
            [*FLOA, "--api", "local", "--color", "never", str(qa)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT 200 3" in result.stdout


def test_override_route_beats_builtin() -> None:
    result = _run_qa(
        "function QuickApp:onInit()\n"
        "  api.registerEndpoint('GET', '/devices/{id}', function(req)\n"
        "    return {fake=true, id=tonumber(req.params.id)}, 200\n"
        "  end, true)  -- override: the module owns this endpoint now\n"
        "  setTimeout(function()\n"
        "    local d, s = api.get('/devices/1')\n"
        "    print('RESULT', s, d and d.fake, d and d.id)\n"
        "    exit(s == 200 and d.fake == true and d.id == 1 and 0 or 1)\n"
        "  end, 20)\n"
        "end\n"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "true 1" in result.stdout  # the FAKE won over the real device


def test_example_alarm_panel_deployed_as_qa() -> None:
    # v2: the mock alarm panel deployed AS A QA (its UI is a sim device),
    # a separate consumer QA resolves its api.* calls through the panel's
    # override routes — delayed arming + refreshState events end to end
    result = subprocess.run(
        [
            *FLOA,
            "--api",
            "local",
            "--color",
            "never",
            "examples/alarm-panel.lua",
            "examples/uses-alarm-panel.lua",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ARM 202" in result.stdout
    assert "EVENT false" in result.stdout  # the arming phase
    assert "EVENT true" in result.stdout  # armed after the exit delay
    assert "PHASE true true" in result.stdout
