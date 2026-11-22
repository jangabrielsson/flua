# Response to issue #5 — class() semantics and loader environments

(Reply draft for GitHub issue #5, flua 0.1.177.)

---

Great field report — both findings checked out, and both turned out to be
documentation gaps rather than divergences. Fixed in 0.1.177: the two traps
are now documented, `dofile` is rebound per QA, and there is a sanctioned
loader.

## 1. `class()` — that is the HC3's contract, now documented

The return-value contract is HC3-faithful, not a flua quirk: `class(name)`
installs the class as the global `name` and returns the parent-setter, and
the class object is read back through `_G[name]`. The strongest evidence was
in the repo next door — Yahue's own production `defClass` does exactly the
`local p = class(name); local cl = _G[name]` dance and runs on a real HC3,
and EventRunner does the same. Fibaro's manual never documents `class()`
itself, which is precisely why it cost source-diving.

Same for `__init`: flua asserts `rawget(t, '__init')`, so a subclass needs
its own constructor — and the real HC3 behaves the same way (every Yahue
subclass redeclares `__init` and chains the parent explicitly:
`HueClass.__init(self, device)`). No code change here; the rule is now
written down in a new **Classes (`class`)** section in USAGE.md with both
patterns.

## 2. Loaders — `dofile` rebound, `_FLUA.loadFile` added

One nuance worth naming: on the real HC3, `dofile`/`load`/`loadfile` are
**nil in QAs** (the sandbox section in USAGE.md lists them, verified live on
5.221) — so any QA using them is flua-only by definition, and there was no
HC3 behavior to diverge from. The trap was which table counts as "the
globals": the QA's `_G` is its env, the shared runtime `_G` has no
`fibaro`/`api`/`net`.

What changed in 0.1.177:

- `dofile(path)` is rebound per QA, exactly like `require` already was — a
  dofile'd file runs in the QA's environment and behaves like a `--%%file`
  include (minus packaging).
- `_FLUA.loadFile(path)` is the sanctioned loader: it returns a chunk bound
  to the QA's env, so harness/tool code never needs to know about the `_G`
  aliasing.
- Raw `load`/`loadfile` stay stock (shared `_G` when no env is passed) —
  documented, with your `loadfile(path, "bt", _G)` workaround called out.

Documented in USAGE.md (new *Loading files into a QA's environment* section
plus the `_FLUA` extensions list), ARCHITECTURE.md, and pinned by a new
test, `tests/test_qa.py::test_qa_dofile_and_loadfile_run_in_qa_env`, which
also asserts the raw-`load` contrast stays as documented.

The working harness (production files loaded unchanged, `HUE:app()` driven
with mocked resources, `flua --check` + virtual time) is exactly the shape
of QA these docs are for — thanks for the field report; it read like the
issues I'd want other harness builders to avoid.
