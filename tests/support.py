"""Shared helpers for the test suite."""

from __future__ import annotations

import signal
import subprocess
from typing import Any


def spawn_for_ctrl_c(*args: Any, **kwargs: Any) -> subprocess.Popen:
    """subprocess.Popen that guarantees the child reacts to SIGINT.

    A suite launched from a backgrounded shell inherits SIGINT as ignored;
    CPython then never installs its KeyboardInterrupt handler, so the child
    swallows Ctrl-C and the exit-contract tests hang until they kill it
    (the release-run -15 failures). Reset SIGINT to default in the child
    before exec.
    """
    preexisting = kwargs.pop("preexec_fn", None)

    def preexec() -> None:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        if preexisting is not None:
            preexisting()

    return subprocess.Popen(*args, preexec_fn=preexec, **kwargs)
