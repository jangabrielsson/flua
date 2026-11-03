# Runtime compatibility

The one place that states what flua runs on and what it targets. For a
running install, `flua --version --machine` prints one JSON line with the
authoritative facts (`version`, `lupa`, `lua`, `python`, `integerBytes`,
`locale`) — when in doubt, check that, not a transcript.

## Python

- **Supported**: 3.11 and newer (`requires-python = ">=3.11"` in
  `pyproject.toml`).
- **Tested in CI** (Ubuntu, every push): 3.11, 3.12, 3.13, 3.14, 3.15 —
  the matrix in `.github/workflows/tests.yml` is the contract; the wheel
  smoke test runs on 3.12.
- **Everyday development**: macOS (the author's daily driver) and Windows
  (community-tested; the flua forum suites run on Windows + 3.12).
- **lupa**: pinned to `lupa>=2.6,<2.7`. 2.6 ships binary wheels for
  cp311–cp314 on the common platforms; cp315 — and exotic platforms — build
  lupa from source and need a C compiler. A source-build failure on install
  is a lupa/platform issue, not a flua one.

## Lua

- **flua runs Lua 5.4** — bundled with lupa 2.6. lupa 2.7+ bundles Lua 5.5,
  whose `const` for-loop variables break HC3 QA code; that is exactly why
  the pin is strict.
- **The HC3 controller runs Lua 5.3** (its own `lua_engine`). QAs that must
  run on both flua and a real controller stick to the **common subset** —
  avoid 5.4-only syntax and 5.4-changed semantics in QA code.
- The LuaLS setup (`.luarc.json` + `.luals/`) targets **Lua 5.4** — it
  documents the flua development loop, not the controller runtime.

## HC3 target

- **Reference firmware: 5.221** — `docs/specs/hc3-api.json` (the distilled
  REST reference) and the device catalog are extracted from a 5.221 rootfs.
- flua tracks the HC3's current behavior; where it intentionally differs,
  the difference is called out in `USAGE.md` / `docs/invariants.md` and
  pinned by a test.

## Transcript convention

Tutorial and README transcripts use placeholders (`flua 0.1.x (Lua 5.4,
Python 3.x)`) so release bumps never rot the docs. Real runs print the
installed versions.
