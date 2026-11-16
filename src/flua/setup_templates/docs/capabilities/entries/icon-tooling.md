---
id: icon-tooling
topic: tooling
title: Icon cache and the icon manager — user icon sets without the HC3 editor
pins:
  - tests/test_tools.py::test_icons_download_enumerates_live_custom_sets
verified: flua 0.1.168
---

# Icon cache and the icon manager — user icon sets without the HC3 editor

The `--tool icons` family manages the shared icon cache
(`~/.flua/icons`, populated once from the HC3):

- `icons download` — fetch the icon library from the HC3 (or a local
  webroot dump with `--dump`); user sets resolve through the usericons
  tree (`/assets/userIcons/...`), and a v1 `/api/icons` call lists
  them — see the `icons-x-fibaro-version` entry.
- `icons ui` — a browser page to list/upload/delete user icon sets on
  the HC3, served locally (it escalates to the next port if busy).

The cache feeds the web view's icon rendering offline; the QA-side
icon APIs (`uploadExternalIconSet` etc.) are listed in the
`--capabilities-json` table under the qa category.
