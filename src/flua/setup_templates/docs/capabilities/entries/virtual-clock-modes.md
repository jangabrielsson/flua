---
id: virtual-clock-modes
topic: runtime
title: The virtual clock — realtime, accelerated, and instant runs
pins:
  - tests/test_virtual_time.py::test_instant_mode_advances_virtual_time
verified: flua 0.1.166
---

# The virtual clock — realtime, accelerated, and instant runs

Everything a QA waits for schedules against the engine's virtual clock;
the mode decides how fast it advances:

- `speed = 1` — realtime; virtual time tracks the wall clock.
- `speed = N` — accelerated: virtual time runs N times faster (the
  builder's simulate uses 600, verify scenarios 6000).
- `speed = inf` / `--instant` — timers fire one deadline at a time and
  the clock jumps to each deadline: hours of simulated time complete at
  CPU speed, and `os.time()` inside a callback reads the callback's own
  deadline (deadline-ordered — the forum-reported bug of a sweep
  advancing past all deadlines is pinned against).
- `--step` — deadline-ordered fast-forward like plua's speedTime.

`os.time()`/`millitime` read the virtual clock, so
`os.time()`-relative delay math (event engines, sunset math) stays
coherent in every mode. A debugger pause does not advance virtual time.
