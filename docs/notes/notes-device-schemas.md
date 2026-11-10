# Note: device schemas — type composition, interface semantics, property type checks (plan)

Status: implemented 2026-11-10 — phases 0–2 done (extraction + artifact,
schema-first skeletons + interface semantics + `--%%interface:`, and the
warn-only property type/enum checks). ADR 0014 is the decision record;
phase 3 (catalog/template verification, device-specific types feeding the
catalog) stays unplanned.

## Context and goal

Original HC3 sources now live locally (gitignored, `HC3_info/`): 189
device-type XMLs (`types/`), 130 interface XMLs (`interfaces/`), and 1173
property JSON schemas (`www/json-schema/`). The type XML declares the
base-type chain, the interfaces a device gets, typed properties with
defaults (and `jsonSchema` refs), and actions with arity; the interface
XML declares the properties/actions an interface adds; the JSON schemas
carry the enums (e.g. `deviceRole`). Today flua ignores all of it:
device skeletons come from a hand-curated hierarchy fallback
(`devices/hierarchy.json` + `skeleton_for`), interfaces are stored with
no semantics (ADR 0012), there is no `--%%interface:` directive, and
property types are unchecked anywhere.

The goal: **preprocess the XML/JSON into flua's own compact schema
artifact, shipped in the wheel, and drive device-structure setup from
it** — type composition on `--%%type:`/`POST /devices`, interface
add/remove semantics (`--%%interface:`, `POST /plugins/interfaces`), and
property type checks (runtime warnings + static `flua --check`).

The access constraint shapes the architecture: the sources stay
gitignored and are never shipped; only the **distilled schema** (facts
flua needs, in our format) is committed. That is also technically the
right format: smaller, faster, no XML parsing at runtime.

## Phase 0 — extraction

`scripts/extract_device_schemas.py` (precedent: `extract_icons.py`,
`extract_hc3_api.py`) reads `HC3_info/{types,interfaces}/*.xml` and
`HC3_info/www/json-schema/properties/*.json`, resolves the `jsonSchema`
refs into inline `enum`s, and emits `src/flua/devices/type_schemas.json`:

```json
{
  "types": {
    "com.fibaro.binarySwitch": {
      "baseType": "com.fibaro.actor",
      "interfaces": ["light", "autoTurnOff"],
      "properties": {
        "value": {"type": "bool"},
        "deviceIcon": {"type": "int", "default": 301},
        "deviceRole": {"type": "string", "enum": ["Light", "Other", ...]}
      },
      "actions": {"turnOn": {"argc": 1}, "turnOff": {"argc": 1}}
    }
  },
  "interfaces": {
    "autoTurnOff": {
      "properties": {"autoOffTimestamp": {"type": "int", "default": 0},
                     "autoOffDefaultTime": {"type": "int", "default": 900}},
      "actions": {"setAutoOff": {"argc": 3, "args": [{"name": "time", "type": "int"}]}}
    }
  }
}
```

- The script runs **locally only** (the sources are gitignored; CI has no
  access). The emitted artifact is committed and covered by a
  **self-consistency test** (every `baseType` resolves, every interface
  reference exists, property types are a known set) — a sync guard
  against the sources is impossible by design.
- Base-type inheritance is flattened at extraction time (a type's
  property set includes its ancestors'), so runtime consumption is a
  plain lookup.

Open: is the extraction script itself committed (pure logic, no data —
leaning yes), or kept local alongside the sources?

## Phase 1 — type composition + interface semantics

- `devices/__init__.py`: load `type_schemas.json`; `skeleton_for` builds
  skeletons from the schema (typed properties with defaults, the
  `interfaces` array, action metadata). `hierarchy.json` remains the
  fallback for types the schema does not know.
- `POST /plugins/interfaces` (`plugin_update_interfaces`): add/remove now
  applies the interface's schema — added properties land with defaults,
  actions become part of the device's action surface, removed interfaces
  drop both. The existing plugin-restart-on-change behavior stays; the
  ADR 0012 pinning tests are updated (storage round-trip + restart) to
  also assert the new semantics.
- New `--%%interface:name[,name...]` directive (config.py, like
  `--%%type:`), applied at QA load through the same code path as the
  REST route — the QA boots with the interface's properties present.
- **ADR 0014** records this, amending 0012: interface semantics are no
  longer undocumented; they derive from the distilled schema. The
  delayed-action REST mechanism (`delay` on the action route,
  `DELETE /devices/action/{timestamp}/{id}`) stays out of scope — the
  schema documents the interface's own properties/actions, not the
  generic delayed-action bookkeeping.

## Phase 2 — property type checks

- **Runtime (warn-only)**: the sim warns when `updateProperty` sets a
  known-typed property to a mismatching type or an out-of-enum value.
  Warn, never reject — the real HC3 silently coerces (write-safety's
  documented behavior), and flua must not break QAs the controller
  accepts.
- **Static (`flua --check`)**: pattern-match `self:updateProperty("p",
  <literal>)` against the schema — literal booleans/numbers/strings only,
  conservative (no type inference); enum literals checked too. This
  catches the typo/type bug before the run.

## Phase 3 (later, unplanned now)

- `--tool catalog` and the `newQA` templates verified/generated against
  the schemas (templates stay hand-written; a consistency check flags
  drift).
- The device-specific type files (`com.fibaro.FGD212` etc.) — real
  device types with their own properties/actions — feeding the catalog
  and the sim-device set.

## Known type-system oddities (mined 2026-11-10)

The 15-year-old type system is cleaner than expected, with drift
concentrated in a few places:

- The **interface layer is conflict-free**: no interface↔type or
  interface↔interface property conflicts (pinned by the consistency
  test) — a device can never get a contradictory spec through its
  interfaces.
- Base-chain overrides that change a type: only two, both sensible
  (`multilevelSwitch.value` bool→int, `temperatureSensor.value`
  real→temperature).
- Legitimate polymorphism: `value` (bool/int/real/temperature across
  families), `state` (bool for switches, string for shutters/multimedia,
  int for the CO detector).
- Drift candidates (same domain, different declaration): `exitTime`
  (bool vs int across two alarm partitions), `port` (int vs string —
  two alarm integrations say string), `input1`/`input2` (bool vs
  string), `Temperature` (real on `weather`, temperature on the other
  weather providers).
- Flua-side impact: none at runtime — the checks are per-device. The
  drift matters only for cross-family work (catalog, template
  verification).

## Open questions

1. Commit the extraction script? (pure logic, no data — leaning yes;
   the alternative keeps every trace of the sources local)
2. Enums in v1? They make both type checks real (deviceRole's list is
   big) at the cost of artifact size — leaning yes, they're the value.
3. Runtime type mismatch: confirm warn-only (never reject)?
4. Scope of types in v1: the generic `com.fibaro.*` set only, or the
   device-specific files (FGD212, FGBS222, ...) too?
5. Action `argc`: metadata only in v1, or should the sim validate
   `fibaro.call` argument counts against it (warn)?
