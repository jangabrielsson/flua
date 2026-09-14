"""Virtual clock — the engine's model of time.

Timers are scheduled against this clock, so Lua's notion of time stays
consistent with timer execution in every mode:

- ``speed = 1``        realtime; virtual time tracks the wall clock
- ``speed = N > 0``    accelerated: virtual time runs N times faster
- ``speed = inf``      instant: real time does not advance virtual time at
                       all; the timer manager jumps virtual time to each
                       timer's deadline when it fires, so scripts that wait
                       for hours/days of simulated time complete instantly

Debugger pauses: the debugger blocks the main thread while waiting for IDE
commands. mobdebug's yield callback calls :meth:`note_pause`, which makes the
next tick discard the accumulated wall time — a pause does not advance
virtual time, so ``os.time()``-based absolute-time math stays consistent.
"""

import math
import time
from datetime import datetime


class VirtualClock:
    def __init__(self, speed: float = 1.0) -> None:
        self.time = time.time()  # virtual seconds, epoch-aligned like os.time()
        self._start = self.time
        self.speed = math.inf if math.isinf(speed) else speed
        self._last = time.monotonic()
        self._frozen_since: float | None = None

    @property
    def instant(self) -> bool:
        return math.isinf(self.speed)

    def tick(self, now_monotonic: float) -> None:
        """Advance virtual time by the real time since the previous tick.

        Called once per pump iteration with ``time.monotonic()``. If the
        debugger froze time since the last tick (note_pause), only the time
        *before* the freeze counts — a debugger pause does not advance
        virtual time.
        """
        if self._frozen_since is not None:
            elapsed = self._frozen_since - self._last  # pre-freeze time only
            self._frozen_since = None
        else:
            elapsed = now_monotonic - self._last
        self._last = now_monotonic
        if not self.instant:
            self.time += elapsed * self.speed

    def note_pause(self) -> None:
        """Freeze virtual time as of now (the debugger is waiting).

        Called (via ``_PY.note_debugger_pause``) just before the debugger's
        blocking socket receive. The next pump tick — which only runs after
        the receive unblocks — advances virtual time only up to the freeze
        point. Pure — never touches Lua state.
        """
        self._frozen_since = time.monotonic()

    def rebase(self) -> None:
        """Restart the tick baseline now (the run's real start).

        Wall time spent on interpreter/engine startup before the first tick
        must not become virtual time: in accelerated mode those milliseconds
        would otherwise jump virtual time far past a --run-for horizon, and
        the horizon cap would kill every timer before it fires.
        """
        self._last = time.monotonic()

    def elapsed(self) -> float:
        """Virtual seconds since the engine started."""
        return self.time - self._start

    def set_start(self, epoch_seconds: float) -> None:
        """Set the virtual time at engine start (e.g. --%%time:start=...)."""
        self.time = float(epoch_seconds)
        self._start = self.time


def parse_start_time(text: str) -> float:
    """Parse a start-time string into epoch seconds.

    Accepts ``2027/10/6 12:00:20``, ``2027-10-06 12:00:20``, or a bare
    date (midnight). Local time, like os.time() on the same machine.
    """
    text = text.strip()
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    raise ValueError(f"cannot parse start time: {text!r}")
