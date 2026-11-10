# 0014 — device structures and interface semantics derive from the distilled type/interface schema

- **Status:** active
- **Date:** 2026-11-10

## Context

The HC3's device-type and interface definitions exist as local sources
(device-type XML with base-type chains, typed properties, defaults and
enum schemas; interface XML with the properties/actions an interface
adds). The sources are **not announceable** (access to them must not
become public precedent), so they stay gitignored and local-only.

ADR 0012 deferred all interface semantics on the grounds that the
behavior was undocumented. Those sources document it. flua therefore
distills them into its own compact artifact and drives device-structure
setup from it.

## Decision

- **The distilled schema is the shipped artifact.** `scripts/
  extract_device_schemas.py` (local-only, run by hand when the sources
  change) reads the local sources and emits `src/flua/devices/
  type_schemas.json` — base-type chains flattened, typed properties with
  defaults and enums, per-type interfaces, action metadata (argc/args).
  The sources are never shipped; only this "compiled" format is
  committed. A self-consistency test (baseTypes resolve, no inheritance
  cycles, interface refs exist, property types known) is the guard —
  freshness against the sources cannot be checked in CI by design.
- **Device skeletons are schema-first.** The schema builds the device
  structure (typed properties at their defaults, every interface the
  type declares expanded — including `quickApp`, the QA-device
  properties). The capture (`devices.json`) and the hierarchy fallback
  remain for types the schema does not know. One deliberate divergence:
  the schema declares `useUiView=true` (the HC3 default); flua keeps the
  legacy layout as the skeleton default — a QA opts in with
  `--%%useUiView:true`.
- **Interfaces have semantics.** `POST /plugins/interfaces` and the new
  `--%%interface:name[,name...]` directive apply the interface's schema:
  add brings its properties (at their defaults) and action metadata;
  remove drops them — except properties the device's type itself
  declares. The plugin restart on interface change is unchanged. Unknown
  interface names keep the ADR 0012 plumbing: stored, no semantics.
- **Property types and enums are checked, warn-only.** The runtime warns
  when `updateProperty` sets a known-typed property to a mismatching
  type or an out-of-enum value; `flua --check` flags literal mismatches
  statically. flua never rejects and never drops the update — the real
  HC3 is believed to silently ignore mismatched updates (field
  knowledge, not yet captured from a live controller; the documented
  coercion case is the setVariable endpoint instead). The sim applies
  the value either way, so the mismatch stays visible.
- `setVariable` is a different surface: `quickAppVariables` is an array
  of `{name = string, value = anything}` entries — the value slot is
  polymorphic by design, which is why the documented value coercion
  (numeric-looking strings become numbers) exists there and the schema
  type checks stop at the array boundary.

## Consequences

- ADR 0012 is amended: its "no semantics" rule now applies to
  *unknown* interfaces only.
- `tests/test_devices.py` (schema consistency, schema skeletons, the
  directive) and `tests/test_api.py` (interface add/remove semantics)
  pin the behavior.
- The artifact is only as fresh as the last local extraction run; the
  self-consistency test catches structural corruption, not staleness.
- Action `argc` is metadata only — the sim does not validate
  `fibaro.call` argument counts (the HC3's own behavior is permissive,
  and QA actions are Lua methods).
