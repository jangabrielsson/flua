# Note: distribution surfaces — brew/winget/scoop and a VS Code extension

Status: idea list, not scheduled. Brought up 2026-10-13; revisit before scoping.

## The goal

Today installing flua means brew + pip (macOS) or Python + pip (Windows) —
the friction the install-macos forum post exists to solve. Two distribution
surfaces can remove it, in increasing order of effort:

1. **Native package managers** — one-command installs, no pip.
2. **A VS Code extension** — marketplace install, bundled runtime, no
   Python at all; the extension then owns run/debug/viewer end to end.

## 1. Native package managers (the cheap 80%)

### macOS — Homebrew

`brew tap jangabrielsson/flua && brew install fibaro-flua`. The formula
vendors a venv (or depends on `python@3.x` and installs the wheel into
`opt/fibaro-flua`), symlinking `flua` into `bin`. No signing needed (brew
builds from source locally). This alone removes pip from the mac story.

### Windows — three candidates (the brew analogues)

- **winget** (Windows Package Manager) — Microsoft's official one, built
  into Windows 11. Most discoverable; `winget install <id>`. Packages via
  manifest PRs to the community repo, or a private repo/`winget configure`.
- **Scoop** — user-space, no admin rights, JSON manifests in a git bucket
  (`scoop install fibaro-flua`). Dev-tool friendly; fits the no-fuss
  audience. Extras: portable/zip installs.
- **Chocolatey** (choco) — the oldest; needs its own install; admin-ish.

For all three the payload is the same question: (a) a manifest that
declares Python as a dependency and runs `pip install fibaro-flua`
(simplest, but pulls the whole Python install UX), or (b) a **portable
self-contained build** (PyInstaller exe in a zip — no admin, no Python,
`PATH` entry optional). (b) is the better user experience and doubles as
the artifact the VS Code extension would bundle anyway — so building the
portable artifact first serves both paths.

## 2. The VS Code extension (the polished later step)

flua cannot run in VS Code's Node extension host, so the extension spawns a
self-contained flua executable (Python + lupa/Lua 5.5 via PyInstaller, one
build per platform: macOS arm64/x64, Windows x64). The extension ships
platform-specific VSIXs (`targetPlatform` in package.json) or downloads the
right binary on first use (the Python/C++ extension model).

- **V1 scope**: bundled runtime, Run/Debug launch configs pointing at the
  bundled binary (PATH problem gone forever), the UI viewer in a webview
  panel, `--tool setup` as an extension command.
- **Later**: bundle LuaLS + flua's type definitions + `--%%` grammar for
  completion/diagnostics; sim tree view; output channels with problem
  matchers; own debug adapter (today debugging depends on the third-party
  `lua-mobdebug` extension — declare it as an extensionDependency in v1).
- **Costs (the real work)**: code signing — macOS Gatekeeper/notarization
  (Apple developer account), Windows SmartScreen warnings for unsigned
  binaries (EV cert for instant trust); a CI matrix building both platforms
  per release; marketplace publishing (Microsoft publisher account).
  Without signing it still works, with right-click/first-run friction —
  but "one click" is the pitch.

## Sequencing recommendation

1. Homebrew formula (days) + winget/scoop package of the portable build
   (days — and the portable artifact is prerequisite work anyway).
2. VS Code extension (weeks, mostly signing + CI + marketplace, not flua
   code).

## Open questions

- Portable build: PyInstaller or Nuitka? Size, startup time, and lupa's C
  extension bundling need a spike.
- winget: community repo PR vs private source; package id ownership.
- Whether the extension should be open-source (publish via the existing
  GitHub account) — presumably yes.
- Does the VS Code extension replace `--tool setup` or call it? (Call it —
  the skills/AGENTS.md remain the agent-knowledge layer.)
