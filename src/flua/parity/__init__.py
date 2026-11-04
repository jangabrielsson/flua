"""flua parity harness: capture against a real HC3, replay offline.

Currently holds the comparison engine (``normalize``) shared by the live
compat suite; the capture/replay tooling lands here as it is built.
"""

from flua.parity.normalize import drift, shape

__all__ = ["shape", "drift"]
