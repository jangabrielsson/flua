# 0008 — `.fqa` files are directly runnable as scripts

- **Status:** active
- **Date:** 2026-10-16

## Context

Testing a package you just downloaded from the HC3 (or built with
`--tool pack`) meant unpacking it first — `flua --tool unpack`, then run the
unpacked main. Agents and users alike want to point flua at the artifact
itself.

## Decision

A `*.fqa` script argument is detected by extension and unpacked to a temp
directory (cleaned at engine stop) via `engine.fqa_to_files` — the same
machinery the upload path uses — and the generated main runs through the
standard pipeline. The regenerated `--%%` header carries name, type,
properties, UI rows, and `--%%file` extras; the QA's own directives ride
along. `flua --check file.fqa` checks the unpacked package. Package
`initialInterfaces` are applied to the device at load (`_prepare_qa`),
mirroring `import_qa`.

## Consequences

- `flua --api local myqa.fqa` and `flua --check myqa.fqa` work with no
  intermediate step (documented in USAGE.md).
- Temp-dir ownership: `_FQA_UNPACK_DIRS` registers the base dir with the
  engine (`track_temp_dir`) — no leftovers after a run; check mode cleans
  up itself.
- Pins: `tests/test_dx.py::test_fqa_as_script_runs_the_packaged_qa`,
  `test_fqa_as_script_check`, `test_fqa_as_script_bad_package_errors`,
  `test_fqa_as_script_applies_initial_interfaces`.
