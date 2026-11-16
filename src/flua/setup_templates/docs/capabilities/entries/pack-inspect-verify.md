---
id: pack-inspect-verify
topic: tooling
title: pack, inspectFQA, and pack --verify — trust the artifact
pins:
  - tests/test_tools.py::test_inspect_fqa_reports_pack_contents
  - tests/test_tools.py::test_pack_verify_reports_and_checks
verified: flua 0.1.166
---

# pack, inspectFQA, and pack --verify — trust the artifact

The package pipeline an agent should run before claiming a QA is ready:

- `flua --tool pack main.lua` — builds the `.fqa` (package values
  baked, `--%%file` extras included, identity properties carried).
- `flua --tool inspectFQA my.fqa [--json]` — what the package
  actually contains: inventory, variables, leak scan. The second time
  agents asked for this, it became a tool.
- `flua --tool pack qa.lua --verify` — pack, then inspect the
  artifact in one step (placeholder/leak checks).

Agents want to *see* what got packed rather than trust it — the
`--verify` round trip closes that loop. Pair with `flua --check
file.lua` for static analysis before packing.
