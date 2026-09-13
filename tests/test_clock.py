"""Unit tests for the virtual clock."""

import math
import time as time_mod

from flua.clock import VirtualClock, parse_start_time


def test_parse_start_time_formats() -> None:
    from datetime import datetime

    expected = datetime(2027, 10, 6, 12, 0, 20).timestamp()
    assert parse_start_time("2027/10/6 12:00:20") == expected
    assert parse_start_time("2027-10-06 12:00:20") == expected
    assert parse_start_time(" 2027/10/6 12:00:20 ") == expected
    assert parse_start_time("2027/10/6") == datetime(2027, 10, 6).timestamp()


def test_parse_start_time_rejects_garbage() -> None:
    import pytest

    with pytest.raises(ValueError, match="cannot parse start time"):
        parse_start_time("not a time")


def test_clock_set_start() -> None:
    import pytest

    clock = VirtualClock()
    epoch = time_mod.time() + 3600  # one hour in the future
    clock.set_start(epoch)
    assert clock.time == epoch
    assert clock.elapsed() == 0  # elapsed still measures since start
    clock.tick(time_mod.monotonic() + 1)
    assert clock.time == pytest.approx(epoch + 1)  # advances from the new start

import pytest

from flua.clock import VirtualClock


def test_realtime_advances_with_wall_clock() -> None:
    c = VirtualClock(1.0)
    start = c.time
    anchor = c._last
    c.tick(anchor + 0.5)
    assert c.time == pytest.approx(start + 0.5)
    c.tick(anchor + 0.7)
    assert c.time == pytest.approx(start + 0.7)


def test_speed_multiplies() -> None:
    c = VirtualClock(4.0)
    start = c.time
    anchor = c._last
    c.tick(anchor + 0.5)
    assert c.time == pytest.approx(start + 2.0)


def test_instant_does_not_advance() -> None:
    c = VirtualClock(math.inf)
    start = c.time
    anchor = c._last
    c.tick(anchor + 50.0)  # any real time at all
    assert c.time == start
    assert c.instant is True


def test_freeze_advances_only_to_freeze_point() -> None:
    c = VirtualClock(1.0)
    start = c.time
    anchor = c._last
    c.tick(anchor + 0.1)
    assert c.time == pytest.approx(start + 0.1, abs=1e-6)
    c._frozen_since = anchor + 0.1  # freeze right at the last tick
    c.tick(anchor + 30.0)  # resumed 29.9 s later: only pre-freeze time counts
    assert c.time == pytest.approx(start + 0.1, abs=1e-6)
    c.tick(anchor + 30.1)  # running again
    assert c.time == pytest.approx(start + 0.2, abs=1e-6)


def test_note_pause_freezes_real_time() -> None:
    import time

    c = VirtualClock(1.0)
    c.note_pause()
    time.sleep(0.02)  # "paused"
    start = c.time
    c.tick(time.monotonic())  # first tick after the pause
    assert c.time == pytest.approx(start, abs=0.01)  # nothing advanced


def test_elapsed_is_virtual() -> None:
    c = VirtualClock(2.0)
    anchor = c._last
    c.tick(anchor + 1.0)
    assert c.elapsed() == pytest.approx(2.0)