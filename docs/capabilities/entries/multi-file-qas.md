---
id: multi-file-qas
topic: packaging
title: Multi-file QAs — --%%file extras and bundled libs travel in the .fqa
pins:
  - docs/tutorial/09-multi-file-qas.md
verified: flua 0.1.166
---

# Multi-file QAs — --%%file extras and bundled libs travel in the .fqa

A QA is one `main.lua` plus any files it declares:

- `--%%file:lib.lua,name` — paths resolve relative to the main file;
  the files travel in the exported/uploaded `.fqa` package.
- A `$` prefix (`--%%file:$lib/sourcetrigger.lua`) loads a library
  bundled with flua — plain Lua that also runs on the HC3, so it ships
  in the package like any QA file.
- `--%%include:defaults.lua` merges another file's directives into the
  header (the `--%%headers:X` plua spelling is accepted).
- Develop in the unpacked format (individual `.lua` files); the HC3
  sees `.fqa` — `--tool pack/unpack` and `uploadQA/downloadQA` do the
  conversion. The tutorial's chapter 9 walks the whole flow.
