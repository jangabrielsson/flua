# flua bug report — Dirigera project conversion (plua → flua)

Collected while checking that the Dirigera QuickApp project and its management
scripts work after converting from plua to flua.

- **flua version**: 0.1.98 (`/opt/homebrew/bin/flua`, Lua 5.4, Python 3.11.13)
- **Date**: 2026-10-28
- **Project**: Dirigera (IKEA Dirigera hub integration for HC3), main QA
  `Dirigera.lua` + `Lib.lua` / `Devices.lua` / `Auth.lua` extras, pinned
  `--%%mode:offline` in the header.

---

## BUG 1 (high): `--api remote` does not win over the main QA's `--%%mode:offline`

The USAGE.md precedence list states *"an explicit `--api local|remote` always
wins"*. In practice, when the **main** QA file has `--%%mode:offline` in its
header, running `flua --api remote` starts the engine online (banner says
`mode online`), but the main QA's own `api.*` calls stay pinned to the
offline sim. This is silent: the QA happily runs against the sim while the
user believes it talks to the real HC3.

Repro (`/tmp/probe.lua`):

```lua
--%%mode:offline
function QuickApp:onInit()
  local info = api.get("/settings/info")
  print("serialNumber:", info and info.serialNumber or "nil")
  _FLUA.exit(0)
end
```

```bash
$ flua --api remote /tmp/probe.lua
🚀 flua 0.1.98 ... mode online
serialNumber: HC3-00000000          # <-- the SIM's serial

$ flua --api remote -D mode:online /tmp/probe.lua
serialNumber: HC3-00000422          # <-- the real HC3's serial
```

`_FLUA.mode` also reports `"offline"` for the QA in the first run.

Expected behavior (options, either is fine):

- `--api remote` overrides the file pin for the main QA too (as documented), or
- the documented per-QA pin stays, but flua then **warns loudly** that the
  main QA's `api.*` calls are pinned to the sim despite `--api remote` —
  currently there is no warning at all.

Workaround today: `flua --api remote -D mode:online Dirigera.lua`.

Related doc nit: USAGE.md documents the offline pin only for *secondary* QAs
("`--%%mode:offline` on a secondary QA pins just that QA's api.* calls to the
sim") — the main QA's pin behavior under `--api remote` is undocumented.

---

## BUG 2 (low): `flua --tool ui` text renderer drops nested containers (legacy viewLayout)

For the classic plua/HC3 row syntax `--%%u:{{button=...},{button=...}}` (two
buttons on one row), the compiled UI is **correct** — the buttons exist in
`viewLayout` (inside a `horizontal` container nested in the section item's
`components`) and in `uiView`, and all `uiCallbacks` are generated. Only the
text output of `flua --tool ui` is wrong: it iterates the section item's
`components` one level deep and skips container entries, so the buttons
simply disappear from the text dump.

Minimal repro (`/tmp/uitest.lua`):

```lua
--%%name:UITest
--%%type:com.fibaro.deviceController
--%%u:{label="titelLabel",text="Dirigera"}
--%%u:{{button="b1",text="Request token",visible=true,onReleased="requestToken"},{button="b2",text="Get token",visible=true,onReleased="getToken"}}
--%%u:{{button="b3",text="List device info",visible=true,onReleased="listDeviceInfo"},{button="b4",text="Restart",visible=true,onReleased="restartQA"}}
--%%u:{multi="select_ID_4",text="Devices",visible=true,onToggled="selectDevices",options={}}
--%%mode:offline
```

Actual output:

```
QA "UITest" (com.fibaro.deviceController)
  label titelLabel "Dirigera"
  space
  space
  space
  select select_ID_4 "Devices" -> onToggled=selectDevices
  space
```

Expected: `button b1 "Request token" -> onReleased=requestToken` etc. for
b1–b4 (as the `uiView` path already renders). Root cause:
`tools/ui.py` `_render_view_layout()` walks `item["components"]` without
descending into nested `horizontal`/`vertical` containers; `_component_line()`
returns `None` for containers, so everything nested inside them is invisible.
(`_components()` used by `--tool ui --json` has the same one-level flatten,
but the JSON dump at least contains the nested container dict with its
buttons, so agents can recover them. `uiView`/`useUiView` paths are flat and
unaffected.)

---

## BUG 3 (minor, fidelity): `plugin.restart()` does not stop the current run

On the HC3, `plugin.restart()` kills the QA immediately — code after the call
never runs. In flua the restart is deferred: execution continues to the end of
the current turn, and only then onInit runs again.

Repro (`/tmp/plugintest.lua`):

```lua
--%%mode:offline
function QuickApp:onInit()
  print("before restart")
  plugin.restart()
  print("after restart (should not print)")
  _FLUA.exit(0)
end
```

```bash
$ flua /tmp/plugintest.lua
before restart
after restart (should not print)   # <-- runs, would not on HC3
[FLUA] restarting QA
before restart                      # <-- restart happens after the turn
```

Real-world impact in this project is low (`getToken()` stores the token, then
calls `plugin.restart()`; the trailing code is harmless), but any QA that
does cleanup/unconditional work after `plugin.restart()` behaves differently
under flua than on the controller. Worth either matching the HC3 (abort the
current turn) or documenting the deferral in USAGE.md.

---

## Observed, not bugs

- **Real network in offline mode**: `net.HTTPClient`/`net.WebSocketClientTls`
  really connect in offline mode (only the HC3 surface is mocked). The
  Dirigera QA booted against the real hub, including a live WSS connection —
  this matched the expectation for this project.
- **plua-style directives** (`-- %%save`, `-- %%proxy`, `-- %%port`): flua
  warns and ignores them. Good. (The leftovers themselves are a project-side
  cleanup item, see appendix.)
- **`flua --tool pack`** works on the project: 6 files
  (`main, sha2, QC, Lib, Devices, Auth`), apiVersion 1.3, vars evaluated.
- **`json.util.InitArray`, `plugin`, `__TAG`, `net.WebSocketClientTls`** are
  all provided by the emulator — the ported code uses them unchanged.

---

## Appendix — project-side leftovers found during the check (not upstream)

For completeness; these are repo issues, not flua bugs:

1. **`Dirigera.lua` header**: three dead plua directives with a space before
   `%%` — `-- %%save:Dirigera.fqa`, `-- %%proxy:true`, `-- %%port=8269`.
   flua warns on each (`flua --check`). They do nothing; remove them.
2. **Management scripts still call plua**:
   - `scripts/project-config.sh` ARTIFACTS: `plua -t pack {SOURCE} {OUTPUT}`
     — **fails on the current sources**: `Library not found: '$sha2.lua'`
     (the `$sha2.lua`/`$qwikchild.lua` system files no longer exist in the
     plua install). flua equivalent that works:
     `flua --tool pack {SOURCE} -o {OUTPUT} -f` (`-f` needed to overwrite
     `dist/Dirigera.fqa`).
   - `scripts/create-release.sh` `check_dependencies` requires the `plua`
     binary and points users to the plua repo — should check `flua`.
   - `scripts/README.md` and `scripts/project-config.sh.example` document
     plua as the packer in several places.
3. **Stale artifacts**:
   - `dist/Dirigera.fqa` (Apr 2026) predates the current sources (Apr/Oct
     2026): all 6 embedded files differ, and the `IP` var is baked as
     `192.168.1.165` while the source says `192.168.50.165`.
   - Root `Dirigera.fqa` (Sep 2025) is an old plua-format package (file
     entries carry `"type":"lua"`, names like `"Auth;"`) — obsolete.
4. **Baked private IP**: `--%%var:IP="192.168.50.165"` packs the literal LAN
   IP into the distributed `.fqa`. Consider a package value
   (`--%%var:IP=expr,"<placeholder>"`) for distribution.
5. **`--%%mode:offline` pin**: because of BUG 1, running this QA against the
   real HC3 through flua requires `-D mode:online` in addition to
   `--api remote`.
