"""Deterministic tests for the virtual-clock timer manager (no lupa needed)."""

from flua.timers import TimerManager


class FakeClock:
    """A clock whose virtual time the test controls directly."""

    def __init__(self) -> None:
        self.time = 1000.0
        self.instant = False


def make_manager(clock: FakeClock, fired: list[int]) -> TimerManager:
    return TimerManager(clock, lambda timer_id: fired.append(timer_id))


def test_fires_when_deadline_reached() -> None:
    clock, fired = FakeClock(), []
    tm = make_manager(clock, fired)
    tm.set_timeout(7, 50)  # deadline 1000.05
    assert tm.fire_due() == 0  # not yet
    clock.time = 1000.05
    assert tm.fire_due() == 1
    assert fired == [7]
    assert tm.active_count() == 0


def test_fire_order_is_deadline_order() -> None:
    clock, fired = FakeClock(), []
    tm = make_manager(clock, fired)
    tm.set_timeout(1, 80)
    tm.set_timeout(2, 20)
    clock.time = 1000.09
    assert tm.fire_due() == 2
    assert fired == [2, 1]


def test_clear_prevents_fire() -> None:
    clock, fired = FakeClock(), []
    tm = make_manager(clock, fired)
    tm.set_timeout(3, 30)
    assert tm.clear_timeout(3) is True
    assert tm.clear_timeout(3) is False
    clock.time = 1000.1
    assert tm.fire_due() == 0
    assert fired == []


def test_rescheduling_same_id_replaces() -> None:
    clock, fired = FakeClock(), []
    tm = make_manager(clock, fired)
    tm.set_timeout(4, 30)
    tm.set_timeout(4, 10)  # same id, earlier deadline
    clock.time = 1000.015
    assert tm.fire_due() == 1
    assert fired == [4]


def test_negative_delay_clamps_to_zero() -> None:
    clock, fired = FakeClock(), []
    tm = make_manager(clock, fired)
    tm.set_timeout(5, -50)  # deadline = now
    assert tm.fire_due() == 1
    assert fired == [5]


def test_instant_mode_jumps_virtual_time() -> None:
    """In instant mode, firing advances V to each timer's deadline."""
    clock, fired = FakeClock(), []
    clock.instant = True
    tm = make_manager(clock, fired)
    tm.set_timeout(1, 10_000)  # deadline 1010
    tm.set_timeout(2, 20_000)  # deadline 1020
    assert tm.fire_due() == 2
    assert fired == [1, 2]
    assert clock.time == 1020.0  # the waiting periods were added to V


def test_qa_timer_attribution() -> None:
    clock = FakeClock()
    fired: list[int] = []
    tm = TimerManager(clock, fired.append)
    tm.set_timeout(1, 100, qa_id=5000)
    tm.set_timeout(2, 200, qa_id=5001)
    tm.set_timeout(3, 300)  # untracked runtime timer
    assert tm.qa_timer_count(5000) == 1
    assert tm.qa_timer_count(5001) == 1
    assert tm.qa_timer_count(9999) == 0
    assert tm.clear_timeout(2) is True
    assert tm.qa_timer_count(5001) == 0  # cleared timers untrack
    clock.time = 1000.5
    assert tm.fire_due() == 2
    assert tm.qa_timer_count(5000) == 0  # fired timers untrack
    assert fired == [1, 3]


def test_stop_clears_pending() -> None:
    clock, fired = FakeClock(), []
    tm = make_manager(clock, fired)
    tm.set_timeout(6, 50)
    tm.stop()
    clock.time = 1000.1
    assert tm.fire_due() == 0
    assert tm.active_count() == 0
