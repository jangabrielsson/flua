# Note: hub profiles — switching between controllers (design)

Status: implemented (2026-11-08) — `flua --tool hub`, the extension's
Switch-hub picker, the `active` marker in `hub list`, and the
`serial:id` per-hub state key. Multi-hub trees and profile encryption
remain out of scope.

## The problem

A user with several HC3s (home, cottage, a customer's) edits `.env` files
by hand to switch. The chain already composes — process env > project
`.env` > `~/.env` — so a project can pin itself while a global default
covers everything else. What's missing is a name for each controller and a
one-command way to switch the global default (or pin a project).

## Design: named profiles in `~/.flua/hubs.json`

One file, one entry per hub:

```json
{
  "home":    {"url": "http://192.168.1.20", "user": "admin", "password": "..."},
  "cottage": {"url": "http://192.168.2.30", "user": "admin", "password": "..."}
}
```

- Created mode 0600, same plaintext-on-disk posture as `.env` today (the
  HC3 itself does not encrypt; secret means "not shown", never "safe").
- Passwords never appear in argv, logs, or `list` output — `add` prompts
  interactively (getpass), so the extension's picker and agents only ever
  see the password-free list.

### The tool: `flua --tool hub`

- `hub add <name> <url> <user> [-f]` — prompts for the password; `-f`
  replaces an existing name.
- `hub list [--json]` — names, urls, and (when reachable) the serial; no
  passwords. The JSON form is the extension's contract.
- `hub switch <name>` — rewrites `HC3_URL`/`HC3_USER`/`HC3_PASSWORD` in
  `~/.env`, preserving every other key (the chain's global default).
  With `--project`, writes the project `.env` instead — pin this folder,
  override the global default.
- `hub remove <name>` — deletes the profile; never touches `.env` (switching
  stays explicit).

Nothing else changes: tools, the engine, `doctor` (which reports where
`HC3_URL` came from), and the extension all keep reading the same chain.
The precedence stays: project pin > global profile > nothing (offline).

## The extension: a switch, not a credential store

The hub view title gains **Switch hub**: `--tool hub list --json` → Quick
Pick (name + url + serial) → `hub switch <name>` in the shared terminal
(so the interactive prompt still works if ever needed) → tree refresh. The
extension never reads the profiles file beyond the password-free list.

The completions surface needs no change: `--tool house` reads the chain on
every fetch, so the next refresh follows the switch automatically.

## Cache and per-hub state — two identity fixes

- The package cache is already keyed by hub **serial** (`hcName`) — the
  serial is identity (the IP may change), so switching naturally separates
  caches, and a hub that moved keeps its cache.
- **Gap 1**: `hub.dirs` (workspaceState: the remembered download folder
  and its unpack-time `modified`) is keyed by **QA id only** — id 57 on
  hub A collides with id 57 on hub B, poisoning the staleness badge. Key
  it `serial:id`.
- **Gap 2**: the serial-fallback-to-URL in `hubSerial()` is fine but
  deserves a pinning comment; keep serial-first.

## Out of scope (named, not forgotten)

- Browsing several hubs simultaneously in one tree (the `hubList` contract
  is single-hub; a multi-hub view would read the same profiles file).
- Encrypting the profiles file (would need a keyring integration per OS —
  a real decision, not a hidden default).

## Verification without a second controller

The tests mock everything (the tool writes files under a fake HOME, like
the existing tool tests); a single real controller still exercises
`add`/`list`/`switch` end to end, and the extension picker shows the one
profile.

## Related

- `docs/notes/notes-vscode-qa-cache.md` — the cache whose keying this fixes
- `src/flua/environment.py` — the chain the tool writes into
- `vscode/src/hub.ts` — the picker and the `serial:id` state key
