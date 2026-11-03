"""The FluaHelper bridge: the emulator's WebSocket server and the
api.helper RPC path (a fake helper client plays the controller's QA)."""

from __future__ import annotations

import asyncio
import base64
import json
import os

import pytest

pytest.importorskip("lupa")

from flua.engine import LuaEngine  # noqa: E402
from flua.helper import Hc3Helper  # noqa: E402
from flua.server import _read_ws_frame, _ws_frame  # noqa: E402


async def _fake_helper(port: int, reply: dict) -> None:
    """A loop-native fake FluaHelper: handshake, answer one RPC, close.
    Bounded by a timeout so a broken flow fails the test instead of
    hanging it."""
    async with asyncio.timeout(10):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write(
            (
                "GET / HTTP/1.1\r\n"
                "Host: helper\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")  # the 101
        frame = await _read_ws_frame(reader)  # the RPC request
        assert frame is not None
        opcode, payload = frame
        assert opcode == 0x1
        request = json.loads(payload)
        writer.write(_ws_frame(0x1, json.dumps({**reply, "id": request["id"]}).encode()))
        await writer.drain()
        writer.close()


async def _fake_helper_fibaro(port: int, reply: dict) -> dict:
    """Fake FluaHelper answering a fibaro-kind RPC; returns the request so
    the test can pin the wire shape (kind/name/args)."""
    async with asyncio.timeout(10):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write(
            (
                "GET / HTTP/1.1\r\n"
                "Host: helper\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")  # the 101
        frame = await _read_ws_frame(reader)
        assert frame is not None and frame[0] == 0x1
        request = json.loads(frame[1])
        writer.write(_ws_frame(0x1, json.dumps({**reply, "id": request["id"]}).encode()))
        await writer.drain()
        writer.close()
        return request


async def wait_until(predicate, timeout: float = 3.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_helper_service_rpc_round_trip() -> None:
    helper = Hc3Helper(0)
    await helper.start()
    try:
        port = helper._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        client = asyncio.create_task(
            _fake_helper(port, {"ok": True, "data": {"x": 1}, "status": 200})
        )
        await wait_until(lambda: helper.connected)
        data, status = await helper.call("GET", "/plugins/5/variables/x", None)
        assert data == {"x": 1} and status == 200
        await client
    finally:
        await helper.stop()


@pytest.mark.asyncio
async def test_helper_service_fibaro_round_trip() -> None:
    helper = Hc3Helper(0)
    await helper.start()
    try:
        port = helper._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        client = asyncio.create_task(
            _fake_helper_fibaro(port, {"ok": True, "values": ["away", 42]})
        )
        await wait_until(lambda: helper.connected)
        values, ok = await helper.call_fibaro("getGlobalVariable", ["HomeStatus"])
        assert ok and values == ["away", 42]
        request = await client
        assert request["kind"] == "fibaro"
        assert request["name"] == "getGlobalVariable"
        assert request["args"] == ["HomeStatus"]
    finally:
        await helper.stop()


@pytest.mark.asyncio
async def test_helper_service_fibaro_error() -> None:
    # a raising fibaro function comes back as ok=false with the message
    helper = Hc3Helper(0)
    await helper.start()
    try:
        port = helper._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        client = asyncio.create_task(
            _fake_helper_fibaro(port, {"ok": False, "values": ["boom"]})
        )
        await wait_until(lambda: helper.connected)
        values, ok = await helper.call_fibaro("call", [88, "turnOn"])
        assert not ok and values == "boom"
        await client
    finally:
        await helper.stop()


@pytest.mark.asyncio
async def test_api_helper_fibaro_through_engine(capsys) -> None:
    # api.helperFibaro suspends like api.helper and unpacks the helper's
    # values on resume
    engine = LuaEngine(config={"helperPort": 0})
    await engine.start()
    try:
        await engine.helper.start()
        port = engine.helper._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        client = asyncio.create_task(
            _fake_helper_fibaro(port, {"ok": True, "values": ["away", 7]})
        )
        await wait_until(lambda: engine.helper.connected)
        engine.start_qa(
            None,
            "setTimeout(function()\n"
            "  local status, n = api.helperFibaro('getGlobalVariable', {'HomeStatus'})\n"
            "  print('FIBARO', status, n)\n"
            "  _FLUA.exit(0)\n"
            "end, 20)\n",
            {},
            "fibaro-caller",
        )
        await wait_until(lambda: not engine.is_running())
        await client
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "FIBARO away 7" in out


@pytest.mark.asyncio
async def test_api_helper_fibaro_error_warns(capsys) -> None:
    engine = LuaEngine(config={"helperPort": 0})
    await engine.start()
    try:
        await engine.helper.start()
        port = engine.helper._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        client = asyncio.create_task(
            _fake_helper_fibaro(port, {"ok": False, "values": ["attempt to index a nil value"]})
        )
        await wait_until(lambda: engine.helper.connected)
        engine.start_qa(
            None,
            "setTimeout(function()\n"
            "  local v = api.helperFibaro('nope', {})\n"
            "  print('FIBARO', v)\n"
            "  _FLUA.exit(0)\n"
            "end, 20)\n",
            {},
            "fibaro-caller",
        )
        await wait_until(lambda: not engine.is_running())
        await client
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "FIBARO nil" in out
    assert "attempt to index a nil value" in out


@pytest.mark.asyncio
async def test_helper_call_unconnected_returns_zero() -> None:
    helper = Hc3Helper(0)
    await helper.start()
    try:
        data, status = await helper.call("GET", "/plugins/5/variables/x", None)
        assert data is None and status == 0
    finally:
        await helper.stop()


@pytest.mark.asyncio
async def test_api_helper_through_engine(capsys) -> None:
    # a QA calling api.helper suspends and resumes with the helper's reply
    engine = LuaEngine(config={"helperPort": 0})
    await engine.start()
    try:
        await engine.helper.start()
        port = engine.helper._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        client = asyncio.create_task(
            _fake_helper(port, {"ok": True, "data": {"name": "heat"}, "status": 200})
        )
        await wait_until(lambda: engine.helper.connected)
        engine.start_qa(
            None,
            "setTimeout(function()\n"
            "  local data, status = api.helper('GET', '/plugins/4357/variables/x', nil)\n"
            "  print('HELPER', status, json.encode(data))\n"
            "  _FLUA.exit(0)\n"
            "end, 20)\n",
            {},
            "helper-caller",
        )
        await wait_until(lambda: not engine.is_running())
        await client
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert 'HELPER 200 {"name":"heat"}' in out


@pytest.mark.asyncio
async def test_api_helper_connects_on_demand(capsys) -> None:
    # the connection is down when a QA calls api.helper: flua discovers the
    # helper on the HC3 (quickAppUuid query), fires its connect action, and
    # waits for the dial-in before sending the RPC — the helper never
    # re-dials on its own
    from flua.helper import helper_identity

    uuid, _version = helper_identity()
    engine = LuaEngine(config={"helperPort": 0})
    await engine.start()
    try:
        await engine.helper.start()
        port = engine.helper._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        calls: list[tuple[str, str, dict | None]] = []

        class FakeRemote:
            base_url = "http://192.168.50.57/"

            def request(self, method: str, path: str, query=None, body=None):
                calls.append((method, path, query))
                if path == "/devices":
                    return [
                        {"id": 9, "properties": {"quickAppUuid": uuid, "model": "1.1.0"}}
                    ], 200
                return None, 202

        fake = FakeRemote()
        engine.hc3 = fake  # type: ignore[assignment]
        engine.api._remote = fake  # type: ignore[attr-defined]

        async def delayed_helper() -> None:
            await asyncio.sleep(0.3)  # dials in after the connect action
            await _fake_helper(port, {"ok": True, "data": {"w": 1}, "status": 200})

        client = asyncio.create_task(delayed_helper())
        engine.start_qa(
            None,
            "setTimeout(function()\n"
            "  local d, s = api.helper('GET', '/plugins/9/variables/x', nil)\n"
            "  print('HELPER', s, json.encode(d))\n"
            "  _FLUA.exit(0)\n"
            "end, 20)\n",
            {},
            "waker",
        )
        await wait_until(lambda: not engine.is_running())
        await client
        # discovered by the property filter in its raw UNQUOTED wire form
        assert ("GET", "/devices", {"property": f"[quickAppUuid,{uuid}]"}) in calls
        assert ("POST", "/devices/9/action/connect", {}) in calls  # asked to connect
    finally:
        engine.hc3 = None  # type: ignore[assignment]
        engine.api._remote = None  # type: ignore[attr-defined]
        await engine.stop()
    out = capsys.readouterr().out
    assert 'HELPER 200 {"w":1}' in out


@pytest.mark.asyncio
async def test_api_helper_unconnected_warns_and_returns_zero(capsys) -> None:
    # no helper connection: (nil, 0) plus one clear warning pointing at
    # --tool installHelper
    engine = LuaEngine(config={"helperPort": 0})
    await engine.start()
    try:
        engine.start_qa(
            None,
            "setTimeout(function()\n"
            "  local data, status = api.helper('GET', '/plugins/4357/variables/x', nil)\n"
            "  print('HELPER', status, data)\n"
            "  _FLUA.exit(0)\n"
            "end, 20)\n",
            {},
            "helper-caller",
        )
        await wait_until(lambda: not engine.is_running())
    finally:
        await engine.stop()
    out = capsys.readouterr().out
    assert "HELPER 0 nil" in out
    assert "installHelper" in out
