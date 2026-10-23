"""--trace: opt-in structured run traces (api/ui/net/timer) for agents.

Each trace lands as an ``{"event": "trace", "data": {"category": ...}}``
entry in the same channel as --syslog (the file and /flua/systemLog), so
one stream gives agents both the lifecycle and the QA's behavior.
"""

import asyncio
import json

import pytest

from flua.engine import LuaEngine


def _trace_entries(path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["event"] == "trace"
    ]


@pytest.mark.asyncio
async def test_trace_categories_filtered_into_syslog(tmp_path) -> None:
    script = tmp_path / "qa.lua"
    script.write_text(
        "--%%name:TraceQA\n"
        "--%%type:com.fibaro.binarySwitch\n"
        "function QuickApp:turnOn() self:updateProperty('value', true) end\n"
        "function QuickApp:onInit()\n"
        "  api.get('/devices')\n"
        "  fibaro.call(self.id, 'turnOn')\n"
        "  setTimeout(function() end, 10000)\n"
        "end\n",
    )

    async def run(trace: str, path) -> None:
        engine = LuaEngine(api_mode="local", trace=trace)
        engine.set_syslog(str(path))
        await engine.start()
        try:
            engine.start_qa(str(script), None, {}, str(script))
            await asyncio.sleep(0.5)
        finally:
            await engine.stop()

    # api + ui enabled: api calls and the device action are traced, timers are not
    syslog = tmp_path / "run1.json"
    await run("api,ui", syslog)
    entries = _trace_entries(syslog)
    assert entries, "no trace entries recorded"
    categories = {e["data"]["category"] for e in entries}
    assert categories == {"api", "ui"}
    api_calls = [e["data"] for e in entries if e["data"]["category"] == "api"]
    assert any("/devices" in call["url"] for call in api_calls)
    assert all("status" in call for call in api_calls)
    actions = [e["data"] for e in entries if e["data"]["category"] == "ui"]
    assert any(a["url"].endswith("/action/turnOn") for a in actions)

    # timer only: timers are traced, api/ui are filtered out
    syslog2 = tmp_path / "run2.json"
    await run("timer", syslog2)
    entries2 = _trace_entries(syslog2)
    categories2 = {e["data"]["category"] for e in entries2}
    assert categories2 == {"timer"}
    kinds = {e["data"]["kind"] for e in entries2}
    assert "start" in kinds and "expire" in kinds
    assert all(e["qa"] == 5000 for e in entries2)


@pytest.mark.asyncio
async def test_trace_all_covers_net(tmp_path) -> None:
    # net traces: a QA's HTTP request to a local server shows up as
    # httpRequest/httpResult with sizes, not payloads
    script = tmp_path / "netqa.lua"
    script.write_text(
        "--%%name:NetQA\n"
        "--%%type:com.fibaro.binarySwitch\n"
        "local http = net.HTTPClient({timeout = 2000})\n"
        "function QuickApp:onInit()\n"
        "  http:request('http://127.0.0.1:1/', {\n"
        "    success = function() exit(0) end,\n"
        "    error = function() exit(0) end,\n"
        "  })\n"
        "end\n",
    )
    engine = LuaEngine(api_mode="local", trace="all")
    syslog = tmp_path / "net.json"
    engine.set_syslog(str(syslog))
    await engine.start()
    try:
        engine.start_qa(str(script), None, {}, str(script))
        await asyncio.sleep(1.0)
    finally:
        await engine.stop()
    entries = _trace_entries(syslog)
    kinds = {e["data"].get("kind") for e in entries if e["data"]["category"] == "net"}
    assert "httpRequest" in kinds and "httpResult" in kinds
