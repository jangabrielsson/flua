---
id: migrate-tool
topic: tooling
title: The migrate tool — one-pass plua-leftover scan
pins:
  - tests/test_tools.py::test_migrate_tool_scans_a_project
verified: flua 0.1.170
---

# The migrate tool — one-pass plua-leftover scan

`flua --tool migrate <project>` scans a project for plua leftovers —
the migration gate for the ex-plua crowd:

- Flags legacy spellings (the `--%%headers:X`/file-colon forms and
  friends), exit 1 on findings, `--json` for agents.
- A clean project exits zero — CI can gate on it.

flua accepts the legacy spellings at runtime (old QAs run with their
intended settings), so the tool is the *carrot* for cleaning them up,
not the stick. The hard-core audience's existing plua projects are the
canonical input; new QAs should start clean.
