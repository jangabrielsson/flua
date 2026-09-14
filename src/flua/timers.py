"""Virtual-clock-driven cooperative timers (setTimeout semantics).

Timers are a deadline queue over the engine's :class:`~flua.clock.VirtualClock`
— no asyncio tasks. The pump ticks the clock and calls ``fire_due()`` every
iteration; a timer fires when virtual time reaches its deadline. In instant
mode the manager jumps virtual time to each deadline as it fires, which is
what makes "wait days, execute now" work.

Timers never touch Lua. A timer that fires invokes an injected
``on_fire(timer_id)`` callback; the engine uses it to enqueue a
``timerExpired`` message that the pump delivers to Lua. Timer IDs are plain
integers and double as Lua callback IDs.
"""

import heapq
import logging
from collections.abc import Callable

from .clock import VirtualClock

logger = logging.getLogger(__name__)


class TimerManager:
    """Schedules one-shot virtual-time timers and reports fires via a callback."""

    def __init__(self, clock: VirtualClock, on_fire: Callable[[int], None]) -> None:
        self._clock = clock
        self._on_fire = on_fire
        self._heap: list[tuple[float, int]] = []  # (deadline, timer_id)
        self._deadlines: dict[int, float] = {}
        self._timer_qa: dict[int, int] = {}  # timer_id -> qa_id attribution
        self._horizon: float | None = None  # absolute virtual run limit

    def set_horizon(self, deadline: float | None) -> None:
        """Cap simulated time at an absolute virtual deadline (fixed --run-for
        and --%%maxhours). Timers beyond it never fire — in instant mode the
        heap would otherwise race far past the limit between CLI polls."""
        self._horizon = deadline

    def set_timeout(self, timer_id: int, delay_ms: int, qa_id: int | None = None) -> None:
        """Schedule a one-shot timer; re-using an existing ID replaces it.

        ``qa_id`` attributes the timer to a QA; None means untracked.
        """
        self.clear_timeout(timer_id)
        deadline = self._clock.time + max(int(delay_ms), 0) / 1000.0
        self._deadlines[timer_id] = deadline
        if qa_id is not None:
            self._timer_qa[timer_id] = qa_id
        heapq.heappush(self._heap, (deadline, timer_id))
        logger.debug("timeout %d scheduled for vtime %.3f", timer_id, deadline)

    def clear_timeout(self, timer_id: int) -> bool:
        """Cancel a pending timer. Returns True if one was pending."""
        if timer_id in self._deadlines:
            del self._deadlines[timer_id]
            self._timer_qa.pop(timer_id, None)
            return True
        return False

    def active_count(self) -> int:
        return len(self._deadlines)

    def qa_timer_count(self, qa_id: int) -> int:
        """Active timers attributed to a QA."""
        return sum(1 for t in self._timer_qa.values() if t == qa_id)

    def cancel_qa(self, qa_id: int) -> int:
        """Cancel all timers attributed to a QA. Returns the number cancelled."""
        ids = [t for t, q in self._timer_qa.items() if q == qa_id]
        for timer_id in ids:
            self.clear_timeout(timer_id)
        return len(ids)

    def fire_due(self) -> int:
        """Fire every timer whose deadline has passed. Returns the count.

        In instant mode virtual time stands still between timers, so the
        manager advances it to each deadline as the timer fires — the
        "waiting period" is added to virtual time.
        """
        fired = 0
        while self._heap:
            deadline, timer_id = self._heap[0]
            if self._deadlines.get(timer_id) != deadline:
                heapq.heappop(self._heap)  # stale entry (cancelled/rescheduled)
                continue
            if self._horizon is not None and deadline > self._horizon:
                break  # beyond the run horizon (fixed --run-for / maxhours)
            if not self._clock.instant and deadline > self._clock.time:
                break  # realtime/speed modes: only fire what is due
            heapq.heappop(self._heap)
            del self._deadlines[timer_id]
            self._timer_qa.pop(timer_id, None)
            if self._clock.time < deadline:
                self._clock.time = deadline  # instant mode: add the wait to V
            try:
                self._on_fire(timer_id)
            except Exception:
                logger.exception("on_fire failed for timer %d", timer_id)
            fired += 1
        return fired

    def stop(self) -> None:
        self._deadlines.clear()
        self._timer_qa.clear()
        self._heap.clear()
