"""Shared fixtures: threaded localhost servers for socket tests, plus a
HOME-isolation fixture.

The autouse fixture isolates HOME for every test: the developer's real
~/.env (HC3 credentials) and ~/.flua.lua must never leak into the suite —
flua's CLI defaults to ONLINE mode when HC3 credentials exist in the
environment, which would silently send plain tests at a production
controller. Live-HC3 runs (HC3_TEST=1) keep the real environment.
"""

import os
import socket
import threading

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    if os.environ.get("HC3_TEST") == "1":
        yield
        return
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield


class EchoServer:
    """Threaded echo server on an ephemeral localhost port.

    Runs in its own threads so tests can make blocking reads on the main
    thread without deadlocking (the server side keeps responding).
    """

    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self.port = self._listener.getsockname()[1]
        self._stop = threading.Event()
        self._clients: list[socket.socket] = []

    def start(self) -> None:
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self) -> None:
        self._listener.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self._clients.append(conn)
            threading.Thread(target=self._echo_loop, args=(conn,), daemon=True).start()

    @staticmethod
    def _echo_loop(conn: socket.socket) -> None:
        conn.settimeout(0.2)
        try:
            while True:
                try:
                    data = conn.recv(4096)
                except TimeoutError:
                    continue
                except OSError:
                    return
                if not data:
                    return
                conn.sendall(data)
        finally:
            conn.close()

    def stop(self) -> None:
        self._stop.set()
        self._listener.close()
        for conn in self._clients:
            try:
                conn.close()
            except OSError:
                pass


@pytest.fixture
def echo_server():
    server = EchoServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def tcp_listener():
    """A listening socket on an ephemeral port; tests accept() on it."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    yield listener
    listener.close()
