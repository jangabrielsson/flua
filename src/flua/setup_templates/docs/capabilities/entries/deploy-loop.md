---
id: deploy-loop
topic: deploy
title: The deploy loop — develop unpacked, the HC3 sees .fqa
pins:
  - tests/test_tools.py::test_pack_unpack_tools_roundtrip
  - tests/test_tools.py::test_upload_file_pushes_single_file
verified: flua 0.1.170
---

# The deploy loop — develop unpacked, the HC3 sees .fqa

You develop in the unpacked format (individual `.lua` files); the HC3
sees `.fqa`. The tool family:

- `uploadQA script.lua [--room ID]` — a new QA from the unpacked
  project (main file + `--%%file` extras); `updateQA 123 script.lua`
  updates an existing QA's files; `uploadFile` pushes ONE file (the
  VS Code task uses it).
- `downloadQA 123 -d project/` — the reverse: unpack a QA from the
  HC3 into individual files (the naming convention resolves main vs
  lib files).
- `pack`/`unpack` do the conversion without a controller
  (`pack-inspect-verify`).

The round trip is pinned (pack → unpack preserves content). Everything
is credential-driven from the `.env` chain; see `multi-file-qas` for
the file layout, `hybrid-routing` for what runs where.
