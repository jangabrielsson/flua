"""``flua --tool ws`` — probe a WebSocket endpoint outside a QA.

Answers "is it the device or the emulator?" in seconds: handshake (ws://
and wss://, self-signed certificates accepted like the HC3), optional
frames sent right after connect (burst testing), a read window, and a soak
with RFC 6455 pings. It drives the SAME WsClient the emulator uses
(src/flua/websocket.py), so what the probe sees is what a QA's
net.WebSocketClient would see.

Exit codes: 0 = handshake and every requested phase completed without a
disconnect; 1 = handshake/send failure; 2 = the connection dropped before
the requested phases finished (soak interrupted, read window cut short).
"""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path
from typing import Any

from ..websocket import _OP_BINARY, _OP_PING, _OP_TEXT, WsClient, _trace_preview

NAME = "ws"
HELP = "probe a WebSocket endpoint: handshake, send frames, soak with pings"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("url", help="ws:// or wss:// endpoint (e.g. wss://player:1443/ws/api)")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME:VALUE",
        help="an extra handshake header, repeatable "
        "(e.g. --header 'Sec-WebSocket-Protocol: mqtt')",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="connect/read timeout (default 5)",
    )
    parser.add_argument(
        "--check-certificate",
        action="store_true",
        help="verify the TLS certificate (the default skips it, like the HC3)",
    )
    parser.add_argument(
        "--send",
        action="append",
        default=[],
        metavar="TEXT",
        help="send a text frame right after connect, repeatable (in order)",
    )
    parser.add_argument(
        "--send-binary",
        action="append",
        default=[],
        metavar="FILE",
        help="send a file's bytes as a binary frame, repeatable (in order with --send)",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="read frames for N seconds after the sends (default 2)",
    )
    parser.add_argument(
        "--soak",
        type=float,
        default=None,
        metavar="SECONDS",
        help="stay connected N more seconds, sending a ping every 10s "
        "(liveness); the connection must survive the whole soak",
    )
    parser.add_argument(
        "--no-close",
        action="store_true",
        help="do not send a closing close frame at the end",
    )


def _trace(line: str) -> None:
    print(line, flush=True)


def run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    headers: dict[str, str] = {}
    for entry in args.header:
        name, sep, value = entry.partition(":")
        if not sep or not name.strip() or not value.strip():
            parser.error(f"--header expects NAME:VALUE, got {entry!r}")
        headers[name.strip()] = value.strip()

    payloads: list[tuple[int, bytes]] = []
    for text in args.send:
        payloads.append((_OP_TEXT, text.encode("utf-8")))
    for path in args.send_binary:
        try:
            payloads.append((_OP_BINARY, Path(path).read_bytes()))
        except OSError as exc:
            parser.error(f"cannot read {path}: {exc}")

    events: list[tuple[str, Any, bool]] = []
    client = WsClient(
        args.url,
        args.timeout,
        lambda event, data, is_binary=False: events.append((event, data, is_binary)),
        headers,
        args.check_certificate,
        _trace,
    )
    try:
        client.connect()
    except Exception as exc:
        print(f"handshake failed: {exc}")
        return 1
    print(f"connected to {args.url}")
    receiver = threading.Thread(target=client.run, daemon=True)
    receiver.start()

    rx: list[tuple[int, bytes]] = []
    state: dict[str, Any] = {"disconnected": False, "reason": None}

    def drained() -> None:
        for event, data, is_binary in list(events):
            events.remove((event, data, is_binary))
            if event == "dataReceived":
                payload = data if is_binary else str(data).encode("utf-8")
                opcode = _OP_BINARY if is_binary else _OP_TEXT
                rx.append((opcode, payload))
                print(f"rx {len(payload)}b {_trace_preview(opcode, payload)}")
            elif event == "disconnected":
                state["disconnected"] = True
                state["reason"] = data
                print(f"disconnected: {data}")

    # sends, in flag order
    for opcode, payload in payloads:
        try:
            if opcode == _OP_BINARY:
                client.send_binary(payload)
            else:
                client.send(payload.decode("utf-8"))
        except Exception as exc:
            print(f"send failed: {exc} (frame: {_trace_preview(opcode, payload)})")
            client.close()
            return 1

    # read window
    deadline = time.monotonic() + args.wait
    while time.monotonic() < deadline:
        drained()
        if state["disconnected"]:
            print("connection dropped during the read window")
            client.close()
            return 2
        time.sleep(0.01)
    drained()

    # soak: the connection must survive; ping every 10s
    if args.soak:
        deadline = time.monotonic() + args.soak
        next_ping = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            drained()
            if state["disconnected"]:
                print(f"connection dropped during the soak: {state['reason']}")
                client.close()
                return 2
            if time.monotonic() >= next_ping:
                try:
                    client._send_frame(_OP_PING, b"flua-ws-probe")
                    next_ping = time.monotonic() + 10.0
                except Exception as exc:
                    print(f"ping failed: {exc}")
                    client.close()
                    return 2
            time.sleep(0.01)

    print(
        f"done: {len(payloads)} frame(s) sent, {len(rx)} received,"
        + (
            f" disconnected ({state['reason']})"
            if state["disconnected"]
            else " still connected"
        )
    )
    if not args.no_close:
        client.close()
    return 0 if not state["disconnected"] else 2
