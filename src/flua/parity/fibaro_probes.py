"""The helperFibaro probe list: fibaro functions run controller-side inside
the FluaHelper QA (the Tier-3 transport) and replayed against the sim's
``fibaro`` table.

Every probe is house-independent — the pinned outcome is the ok/error
contract and the value *types*, never concrete house values:

- ``getName()`` — the helper's context (no args; the HC3 tolerates it —
  the sim's signature check is itself a pinned divergence);
- ``getGlobalVariable("fluaParityProbe")`` — absent on both sides: pins the
  nil-on-absent contract;
- ``getSelfId()`` — not a function on the HC3 (verified live): pins the
  unknown-name error contract;
- ``nope()`` — same contract for a name neither side has.
"""

from __future__ import annotations

# (name, args, note)
FIBARO_PROBES: list[tuple[str, list, str]] = [
    ("getName", [], "no-arg call: the HC3 returns the controller name"),
    (
        "getGlobalVariable",
        ["fluaParityProbe"],
        "absent variable: pins the nil-on-absent contract",
    ),
    ("getSelfId", [], "the HC3 has no such function — pins the error contract"),
    ("nope", [], "a name neither side has — pins the error contract"),
]
