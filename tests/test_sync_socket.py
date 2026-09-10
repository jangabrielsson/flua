"""Unit tests for the blocking sync TCP layer (no lupa needed)."""

import threading
import time

from flua.sync_socket import SyncTCPSockets


def test_connect_write_read_line(echo_server) -> None:
    sc = SyncTCPSockets()
    ok, conn_id = sc.connect("127.0.0.1", echo_server.port)
    assert ok
    assert sc.write(conn_id, "hello\n")[0] is True
    ok, data = sc.read(conn_id, "*l")
    assert ok and data == "hello"
    assert sc.close(conn_id)[0] is True
    assert sc.connection_count() == 0


def test_read_exact_bytes(echo_server) -> None:
    sc = SyncTCPSockets()
    _, conn_id = sc.connect("127.0.0.1", echo_server.port)
    sc.write(conn_id, "abcdef")
    ok, data = sc.read(conn_id, 3)
    assert ok and data == "abc"
    ok, data = sc.read(conn_id, 3)
    assert ok and data == "def"
    sc.close(conn_id)


def test_read_all_until_close(tcp_listener) -> None:
    port = tcp_listener.getsockname()[1]

    def serve_once() -> None:
        conn, _ = tcp_listener.accept()
        data = conn.recv(4096)
        conn.sendall(data)
        conn.close()

    threading.Thread(target=serve_once, daemon=True).start()

    sc = SyncTCPSockets()
    _, conn_id = sc.connect("127.0.0.1", port)
    sc.write(conn_id, "all of it")
    ok, data = sc.read(conn_id, "*a")
    assert ok and data == "all of it"
    sc.close(conn_id)


def test_timeout_returns_timeout(echo_server) -> None:
    sc = SyncTCPSockets()
    _, conn_id = sc.connect("127.0.0.1", echo_server.port)
    sc.set_timeout(conn_id, 0.05)
    ok, err, partial = sc.read(conn_id, "*l")
    assert not ok and err == "timeout" and partial is None
    sc.close(conn_id)


def test_nonblocking_returns_immediately(echo_server) -> None:
    sc = SyncTCPSockets()
    _, conn_id = sc.connect("127.0.0.1", echo_server.port)
    sc.set_timeout(conn_id, 0)  # LuaSocket: 0 = non-blocking
    start = time.monotonic()
    ok, err, partial = sc.read(conn_id, "*l")
    elapsed = time.monotonic() - start
    assert not ok and err == "timeout" and partial is None
    assert elapsed < 0.05
    sc.close(conn_id)


def test_timeout_returns_partial_data(echo_server) -> None:
    sc = SyncTCPSockets()
    _, conn_id = sc.connect("127.0.0.1", echo_server.port)
    sc.write(conn_id, "partial")
    sc.set_timeout(conn_id, 0.05)
    ok, err, partial = sc.read(conn_id, 10)
    assert not ok and err == "timeout" and partial == "partial"
    sc.close(conn_id)


def test_eof_returns_closed(echo_server) -> None:
    sc = SyncTCPSockets()
    _, conn_id = sc.connect("127.0.0.1", echo_server.port)
    # closing the peer: send FIN and make the echo thread drop the connection
    echo_server.stop()
    time.sleep(0.3)
    ok, err, partial = sc.read(conn_id, "*l")
    assert not ok and err == "closed"
    sc.close(conn_id)


def test_bind_accept_roundtrip() -> None:
    server = SyncTCPSockets()
    ok, server_id = server.bind("127.0.0.1", 0)
    assert ok
    _, _ip, port = server.getsockname(server_id)

    def connect_after(delay: float) -> None:
        time.sleep(delay)
        client = SyncTCPSockets()
        ok, conn_id = client.connect("127.0.0.1", port)
        assert ok
        client.write(conn_id, "ping\n")

    threading.Thread(target=connect_after, args=(0.2,), daemon=True).start()

    ok, conn_id = server.accept(server_id)
    assert ok
    ok, data = server.read(conn_id, "*l")
    assert ok and data == "ping"
    server.close(conn_id)
    server.close(server_id)
