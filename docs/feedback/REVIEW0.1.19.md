# Project review: flua 0.1.19

This review looks at three areas: architecture, QuickApp (QA) developer
experience, and contributor experience. The items below are recommendations,
not changes already made.

## Summary

flua has a strong foundation: the single-entry Lua pump is clearly documented,
API routes are separated from simulator state, virtual time supports
deterministic behavior, and most tests use local mocks rather than requiring a
live HC3. The QA tutorial and development tools are also substantial.

The main opportunities are to reduce the responsibilities concentrated in
`LuaEngine`, strengthen offline compatibility and packaging checks, and resolve
conflicting documentation about whether a plain run can contact a real HC3.

## Architecture

### 1. Reduce `LuaEngine` responsibilities incrementally

`LuaEngine` is about 1,750 lines and owns QA lifecycle and file management,
proxy and poller behavior, persistence, network-message handling, and the
message pump. Extract focused collaborators where the existing boundaries are
already clear. Potential seams include QA startup and preparation,
HC3 polling, and pump dispatch.

Keep the single-entry Lua invariant centralized: the pump should remain the
only place that enters Lua. The goal is clearer ownership and more manageable
tests, not a broad redesign of the message protocol.

### 2. Make HC3 compatibility fixtures available in routine CI

The compatibility suite compares response shapes with a live controller and
is intentionally opt-in. Add sanitized, versioned response fixtures for
important HC3 endpoints, and use them in normal CI to detect simulator
regressions without contacting a controller. Keep the live suite as an
additional upstream compatibility check.

## QA developer experience

### 3. Reconcile conflicting documentation about the default mode

The CLI implementation and user guide say that a plain run defaults to the
offline simulator. Some other references still describe online-by-default
behavior, including the architecture guide, test fixture commentary, and the
generated QA-project `AGENTS.md`.

Update those references to match the current behavior. Add a CLI regression
test that proves a plain invocation remains offline even if HC3 credentials
are present. This is the highest-priority recommendation because the
discrepancy affects whether QA code could contact a real controller.

### 4. Align installed-project Lua tooling with the runtime

The repository's `.luarc.json` targets Lua 5.5 and declares HC3 globals, while
the packaged setup template targets Lua 5.4 and disables several useful
diagnostics. Align the template with the supported runtime and the repository
configuration.

Consider shipping Lua Language Server type definitions for `QuickApp`,
`fibaro`, `api`, and network APIs. Add a test that keeps the repository and
packaged configuration in sync.

### 5. Document a repeatable QA-level testing pattern

The project has good internal engine and template tests, but QA developers
could use a standard recipe for testing their own QuickApps against a seeded
simulator. Document a pytest fixture or small helper pattern for launching a
QA and asserting on logs, simulator state changes, actions, and UI events.
Prefer an approach that does not require QA authors to depend directly on
engine internals.

## Contributor experience

### 6. Test the advertised Python support range in CI

CI currently tests Python 3.11 and 3.13, while the project advertises support
from Python 3.11 onward and lists Python 3.12 in package metadata. Add Python
3.12 to the CI matrix, or clearly document a narrower tested support range.
Consider covering each supported minor version.

### 7. Smoke-test the built wheel

CI currently installs the editable checkout. Pip users instead depend on
packaged Lua files, examples, and QA setup templates. Build the wheel in CI,
install it into a clean environment, and smoke-test commands such as
`flua --examples` and `flua --tool setup`.

The existing source-tree tests check template content; a wheel-level test
would also detect packaging omissions.

### 8. Keep the contributor instructions and CI gate aligned

CI runs Ruff lint and pytest. Formatting is documented as an additional step
for larger changes. Consider enforcing `ruff format --check` in CI so the
formatting expectation is consistent and review churn is reduced.

The contributor guide and PR script already provide a focused workflow; this
recommendation extends that existing approach rather than replacing it.

## Suggested order

1. Correct the mode documentation and add the offline-default regression test.
2. Add wheel packaging smoke tests and Python 3.12 CI coverage.
3. Align the Lua language-server setup template and add a sync check.
4. Add simulator compatibility fixtures for commonly used HC3 endpoints.
5. Document a QA-level testing pattern.
6. Extract `LuaEngine` responsibilities in small, test-backed steps.
7. Decide whether format checking should be part of the required CI gate.
