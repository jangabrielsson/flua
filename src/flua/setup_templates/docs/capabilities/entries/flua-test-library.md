---
id: flua-test-library
topic: testing
title: Self-asserting QAs — the flua-test library and --strict-tests
pins:
  - tests/test_qa.py::test_example_self_test_passes_and_exits_zero
  - tests/test_dx.py::test_strict_tests_sticky_callback_failure
verified: flua 0.1.170
---

# Self-asserting QAs — the flua-test library and --strict-tests

The verification-legibility surface (ADR 0013's second promise): a QA
can assert its own behavior and exit with the verdict as the exit code:

- The `flua-test` library (`$flua-test` bundled lib,
  `examples/selfTest.lua` as the living fixture) turns assertions into
  PASS/FAIL lines and a final exit code — a test scaffold an agent can
  drop into any QA project.
- `--strict-tests` (CI mode, `--%%strict-tests:true` as a directive)
  makes **unhandled callback errors fail the run with exit 1**, sticky
  — a silently swallowed error in a timer/UI/net callback becomes a
  red build instead of a mystery.
- `--result-json` renders the run's verdicts machine-readably, so a
  requirements checklist (each requirement → PASS/FAIL) is one
  generation step away from an agent's test run.

The recipe verify scenarios (`recipe-verify-scenarios`) are the same
idea in declarative form; both exit 0/1 for CI.
